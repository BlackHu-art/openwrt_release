#!/usr/bin/env python3
"""Check the shared Xray core against complete, real plugin generators.

Only router-facing UCI, filesystem and command boundaries are substituted.
Set XRAY_TEST_BINARY to an explicitly downloaded core to run config validation;
the test never downloads binaries, starts a service, or binds a listener.
"""
import base64
import copy
from functools import lru_cache
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from fetch_xray_test_core import VERSION as TARGET_VERSION
import test_ssrplus_core_config as ssr_core
import test_ssrplus_subscription as ssr_subscription


ROOT = Path(__file__).resolve().parents[1]
UUID = "12345678-1234-1234-1234-123456789abc"
# Valid public key from `xray x25519 -i` with an all-zero 32-byte test input.
# This public fixture is only parsed by `run -test`; no handshake is performed.
REALITY_PUBLIC_KEY = "L-V9o0fNYkMVKNqsX7spBzD_9oSvxM_C7ZCZX1jLO3Q"
TRANSPORTS = ("raw", "ws", "httpupgrade", "grpc")

if os.environ.get("REQUIRE_XRAY_TEST_CORE") == "1" and not os.environ.get("XRAY_TEST_BINARY"):
    raise RuntimeError("Xray is required by REQUIRE_XRAY_TEST_CORE; set XRAY_TEST_BINARY")

if os.environ.get("XRAY_TEST_BINARY") and not ssr_subscription.LuaRuntime:
    raise RuntimeError("XRAY_TEST_BINARY requires lupa.lua51; refusing to skip the real core gate")


def check_core_config(binary, config, path):
    payload = json.dumps(config)
    if os.name == "nt":
        # The native Windows core can see different temporary-file bytes from
        # Python on managed desktops. Feed the complete generated JSON through
        # Xray's official stdin loader; Linux keeps testing file loading.
        command = [binary, "run", "-test", "-config", "stdin:", "-format", "json"]
        return subprocess.run(command, input=payload, capture_output=True, text=True,
                              encoding="utf-8", timeout=20)
    path.write_text(payload, encoding="utf-8")
    return subprocess.run([binary, "run", "-test", "-config", str(path)],
                          capture_output=True, text=True, encoding="utf-8", timeout=20)


def _lua_function(source, name):
    match = re.search(r"(?ms)^function " + re.escape(name) + r"\(.*?^end\b", source)
    if not match:
        raise AssertionError("missing upstream API helper: " + name)
    return match.group(0)


def _is_ip(value, version=None):
    try:
        address = ipaddress.ip_address(value)
        return version is None or address.version == version
    except ValueError:
        return False


def generate_passwall_config(plugin, node=None, *, runtime_args=None, sections=None,
                             entrypoint="gen_config", core_version=TARGET_VERSION):
    """Execute the complete imported util_xray.lua with read-only UCI fixtures."""
    package = ROOT / "maintenance/plugins" / plugin / ("luci-app-" + plugin)
    source = (package / "luasrc" / plugin / "util_xray.lua").read_text(encoding="utf-8")
    api_source = (package / "luasrc" / plugin / "api.lua").read_text(encoding="utf-8")
    lua = ssr_subscription.LuaRuntime(unpack_returned_tuples=True)
    globals_ = lua.globals()
    values = copy.deepcopy(sections or {})
    if node:
        values[node[".name"]] = copy.deepcopy(node)

    def lua_value(value):
        return lua.table_from(value, recursive=True) if isinstance(value, (dict, list)) else value

    def get_section(section, option=None):
        value = copy.deepcopy(values.get(section))
        if option is not None:
            value = (value or {}).get(option)
        return lua_value(value)

    def foreach(kind, callback):
        for value in values.values():
            if value.get(".type") == kind:
                callback(lua_value(copy.deepcopy(value)))

    def forbidden(*args):
        raise AssertionError("unexpected generator OS operation: " + repr(args))

    def command_output(command):
        uci_addresses = ("uci show " + plugin +
                         r''' | sed -n "s/.*\.\(address\|download_address\)='\([^']*\)'/\2/p" | sort -u''')
        if command == uci_addresses:
            return "\n".join(sorted({section[key] for section in values.values()
                                      for key in ("address", "download_address") if section.get(key)}))
        if plugin == "passwall2" and command == (
                '''uci show passwall2 | grep ".address=" | cut -d "'" -f 2 | grep "[a-zA-Z]$" | sort -u'''):
            return "\n".join(sorted({section["address"] for section in values.values()
                                      if re.search(r"[a-zA-Z]$", section.get("address", ""))}))
        return forbidden(command)

    globals_.py_get = get_section
    globals_.py_foreach = foreach
    globals_.py_forbidden = forbidden
    globals_.py_exec = command_output
    globals_.py_version = core_version
    globals_.py_hostname = lambda value: bool(value) and not _is_ip(value)
    globals_.py_ipv6 = lambda value: _is_ip(value, 6)
    globals_.py_local_ip = lambda value: _is_ip(value) and ipaddress.ip_address(value).is_private
    globals_.py_stringify = lambda value, *args: json.dumps(ssr_core.lua_to_python(value))
    lua.execute(r'''
module = function() end
arg = {}
api = {c_config="fixture", CACHE_PATH="/tmp/fixture", TMP_PATH="/tmp/fixture",
    sys={call=py_forbidden, exec=py_exec},
    fs={readfile=function() return nil end, access=function() return false end},
    jsonc={stringify=py_stringify},
    datatypes={hostname=py_hostname},
    get_app_version=function(name) assert(name == "xray"); return py_version end,
    uci_get_c=py_get, uci_foreach_c=py_foreach,
    cacheFileCompareToLogic=function() return true end,
    vps_domain_exclude=function() return false end,
    is_ipv6=py_ipv6, is_local_ip=py_local_ip,
    finded_com=function() return nil end,
    log=function() end}
require = function(name)
    assert(name:match("^luci%.passwall2?%.api$"), "unexpected module " .. name)
    return api
end
os.execute = py_forbidden
io.popen = py_forbidden
io.open = py_forbidden
''')
    for name in ("split", "trim", "clone", "cleanEmptyTables", "UrlDecode"):
        lua.execute(_lua_function(api_source, name) + "\napi." + name + "=" + name)
    lua.execute(source)
    arguments = {"flag": "fixture", "node": node[".name"] if node else None,
                 "local_socks_address": "127.0.0.1", "local_socks_port": "12345",
                 "no_run": "1"}
    arguments.update(runtime_args or {})
    result = globals_[entrypoint](lua_value(arguments))
    return json.loads(result) if isinstance(result, str) else ssr_core.lua_to_python(result)


def passwall_node(protocol, transport="raw"):
    return {".type": "nodes", ".name": "candidate", "type": "Xray",
            "protocol": protocol, "address": "192.0.2.1", "port": "443",
            "uuid": UUID, "password": "fixture-secret", "method": "aes-128-gcm",
            "ss_method": "aes-128-gcm",  # Passwall2's UCI field differs from Passwall.
            "transport": transport, "tls": "1", "tls_serverName": "tls.example",
            "tls_allowInsecure": "0", "ws_host": "cdn.example", "ws_path": "/fixture",
            "httpupgrade_host": "cdn.example", "httpupgrade_path": "/fixture",
            "grpc_serviceName": "fixture-service", "grpc_mode": "gun"}


def _subscribe_ssr_node(uri):
    subscriber = ssr_subscription.SubscriptionRegressions()
    subscriber.setUp()
    try:
        subscriber.sections["subscribe"].update(ss_type="v2ray", xray_tj_type="v2ray")
        subscriber.installed_cores = set(ssr_core.CORE_BINARIES)
        subscriber.downloads[ssr_subscription.URL_A] = base64.b64encode(uri.encode()).decode()
        subscriber.files.pop("/tmp/sub_md5_" + ssr_subscription.group_hash(ssr_subscription.URL_A), None)
        status = subscriber.run_subscriber()
        if status:
            raise AssertionError("real SSRPlus subscription failed: " + repr(subscriber.logs))
        return next(copy.deepcopy(node) for node in subscriber.persisted.values()
                    if node.get("grouphashkey") == ssr_subscription.group_hash(ssr_subscription.URL_A))
    finally:
        subscriber.doCleanups()


@lru_cache(maxsize=1)
def generated_configs():
    """Return named actual outputs; no post-generation compatibility rewriting."""
    cases = {}
    for plugin in ("passwall2",):
        for protocol in ("vless", "trojan", "shadowsocks"):
            for transport in TRANSPORTS:
                label = "/".join((plugin, protocol, transport, "tls"))
                cases[label] = generate_passwall_config(plugin, passwall_node(protocol, transport))
        vmess = passwall_node("vmess", "ws")
        vmess["security"] = "auto"
        cases[plugin + "/vmess/ws/tls"] = generate_passwall_config(plugin, vmess)
        reality = passwall_node("vless")
        reality.update(reality="1", reality_publicKey=REALITY_PUBLIC_KEY,
                       reality_shortId="0123456789abcdef", fingerprint="chrome",
                       flow="xtls-rprx-vision")
        cases[plugin + "/vless/raw/reality"] = generate_passwall_config(plugin, reality)
        # These newer generator paths used to evade the shared-core gate.
        masque = passwall_node("masque")
        masque.pop("password")  # Anonymous MASQUE does not send HTTP Basic auth.
        masque.update(masque_path="/.well-known/masque/{ipproto}/{target}/")
        cases[plugin + "/masque"] = generate_passwall_config(plugin, masque)
        for guise in ("none", "srtp", "dns"):
            mkcp = passwall_node("vless", "mkcp")
            mkcp.update(mkcp_guise=guise, mkcp_seed="fixture-seed", mkcp_domain="mask.example")
            cases[plugin + "/vless/mkcp/" + guise] = generate_passwall_config(plugin, mkcp)
        for obfs in ("salamander", "gecko"):
            hy2 = passwall_node("hysteria2")
            hy2.update(hysteria2_auth_password="fixture-auth", hysteria2_obfs_type=obfs,
                       hysteria2_obfs_password="fixture-obfs", hysteria2_obfs_MinPacketSize="600",
                       hysteria2_obfs_MaxPacketSize="1100")
            cases[plugin + "/hysteria2/" + obfs] = generate_passwall_config(plugin, hy2)
        xhttp = passwall_node("vless", "xhttp")
        xhttp.update(xhttp_host="cdn.example", xhttp_path="/fixture", xhttp_mode="auto")
        cases[plugin + "/vless/xhttp/tls"] = generate_passwall_config(plugin, xhttp)
        cases[plugin + "/socks-http-helper"] = generate_passwall_config(
            plugin, entrypoint="gen_proto_config", runtime_args={
                "local_http_port": "12346", "server_proto": "socks",
                "server_address": "192.0.2.1", "server_port": "1080"})
        runtime = {"redir_port": "12347", "tcp_proxy_way": "tproxy", "dns_listen_port": "15353",
                   "direct_dns_udp_server": "223.5.5.5", "direct_dns_port": "53",
                   "direct_dns_udp_port": "53", "remote_dns_tcp_server": "1.1.1.1",
                   "remote_dns_tcp_port": "53", "remote_dns_query_strategy": "UseIP"}
        cases[plugin + "/transparent-tcp-udp-dns"] = generate_passwall_config(
            plugin, passwall_node("vless"), runtime_args=runtime)
        shunt = {".type": "nodes", ".name": "shunt", "type": "Xray", "protocol": "_shunt",
                 "default_node": "candidate", "direct_rule": "_direct", "domainStrategy": "IPOnDemand"}
        sections = {"candidate": passwall_node("trojan"), "direct_rule": {
            ".type": "shunt_rules", ".name": "direct_rule", "remarks": "fixture direct",
            "domain_list": "domain:direct.example", "ip_list": "192.0.2.0/24", "network": "tcp,udp"}}
        cases[plugin + "/shunt-dns"] = generate_passwall_config(
            plugin, shunt, runtime_args=runtime, sections=sections)
    for protocol in ("ss", "vless", "trojan"):
        for transport in TRANSPORTS:
            uri = ssr_core.link(protocol, "type=" + transport +
                                "&security=tls&sni=tls.example&host=cdn.example&path=%2Ffixture&serviceName=fixture-service")
            node = _subscribe_ssr_node(uri)
            cases["/".join(("ssrplus", protocol, transport, "tls"))] = ssr_core.generate_core_config(
                node, xray_version=TARGET_VERSION)
    vmess_uri = "vmess://" + base64.b64encode(json.dumps({
        "v": "2", "ps": "VMess TLS fixture", "add": "ss.example", "port": "443",
        "id": UUID, "aid": "0", "scy": "auto", "net": "ws", "type": "none",
        "host": "cdn.example", "path": "/fixture", "tls": "tls", "sni": "tls.example"
    }).encode()).decode()
    cases["ssrplus/vmess/ws/tls"] = ssr_core.generate_core_config(
        _subscribe_ssr_node(vmess_uri), xray_version=TARGET_VERSION)
    reality_uri = ssr_core.link("vless", "type=raw&security=reality&sni=tls.example&fp=chrome&pbk=" +
                               REALITY_PUBLIC_KEY + "&sid=0123456789abcdef&flow=xtls-rprx-vision")
    cases["ssrplus/vless/raw/reality"] = ssr_core.generate_core_config(
        _subscribe_ssr_node(reality_uri), xray_version=TARGET_VERSION)
    node = _subscribe_ssr_node(ssr_core.link("vless", "type=raw&security=tls&sni=tls.example"))
    for mode in ("tcp", "udp", "tcp,udp"):
        cases["ssrplus/transparent-" + mode] = ssr_core.generate_core_config(
            node, runtime_args=[mode, "12347", "0"], xray_version=TARGET_VERSION)
    cases["ssrplus/socks-only"] = ssr_core.generate_core_config(
        node, runtime_args=["tcp", "0", "12345"], xray_version=TARGET_VERSION)
    node.update(domain_resolver="tcp", domain_resolver_dns="223.5.5.5:53")
    cases["ssrplus/node-dns"] = ssr_core.generate_core_config(node, xray_version=TARGET_VERSION)
    return cases


@unittest.skipUnless(ssr_subscription.LuaRuntime, "optional lupa.lua51 is required")
class SharedXrayGeneratorContracts(unittest.TestCase):
    def test_new_transport_parameters_reach_the_final_config(self):
        cases = generated_configs()
        outbound = cases["passwall2/masque"]["outbounds"][0]
        self.assertEqual(outbound["protocol"], "masque")
        self.assertEqual(outbound["streamSettings"]["method"], "masque")
        self.assertEqual(outbound["streamSettings"]["masqueSettings"]["path"],
                         "/.well-known/masque/{ipproto}/{target}/")
        mask = cases["passwall2/vless/mkcp/dns"]["outbounds"][0]["streamSettings"]["finalmask"]
        self.assertIn({"type": "mkcp-legacy", "settings": {"value": "fixture-seed"}}, mask["udp"])
        gecko = cases["passwall2/hysteria2/gecko"]["outbounds"][0]["streamSettings"]["finalmask"]["udp"][0]
        self.assertEqual(gecko["type"], "salamander")
        self.assertEqual(gecko["settings"]["password"], "fixture-obfs")

    def test_generated_minimum_versions_fit_shared_core(self):
        target = tuple(map(int, TARGET_VERSION.split(".")))
        for label, config in generated_configs().items():
            with self.subTest(config=label):
                self.assertTrue(config["inbounds"])
                self.assertTrue(config["outbounds"])
                if label.startswith(("passwall2/",)):
                    required = tuple(map(int, config["version"]["min"].split(".")))
                    self.assertLessEqual(required, target)

    def test_transparent_dns_and_shunt_cases_exercise_the_named_paths(self):
        cases = generated_configs()
        for plugin in ("passwall2",):
            with self.subTest(plugin=plugin):
                config = cases[plugin + "/transparent-tcp-udp-dns"]
                self.assertTrue(config["dns"]["servers"])
                self.assertTrue(any(inbound["protocol"] in ("dokodemo-door", "tunnel")
                                    for inbound in config["inbounds"]))
                shunt = cases[plugin + "/shunt-dns"]
                self.assertTrue(any("domain:direct.example" in rule.get("domains", [])
                                    for rule in shunt["routing"]["rules"]))
        self.assertTrue(cases["ssrplus/node-dns"]["dns"]["servers"])

    def test_vmess_and_reality_cases_exercise_the_named_protocols(self):
        cases = generated_configs()
        for plugin in ("passwall2", "ssrplus"):
            with self.subTest(plugin=plugin):
                vmess = cases[plugin + "/vmess/ws/tls"]["outbounds"][0]
                self.assertEqual(vmess["protocol"], "vmess")
                self.assertEqual(vmess["streamSettings"]["security"], "tls")
                self.assertEqual(vmess["streamSettings"]["tlsSettings"]["serverName"], "tls.example")
                reality = cases[plugin + "/vless/raw/reality"]["outbounds"][0]
                self.assertEqual(reality["protocol"], "vless")
                self.assertEqual(reality["streamSettings"]["security"], "reality")
                self.assertEqual(reality["streamSettings"]["realitySettings"]["publicKey"], REALITY_PUBLIC_KEY)
                self.assertEqual(reality["streamSettings"]["realitySettings"]["shortId"], "0123456789abcdef")

    @unittest.skipUnless(os.environ.get("XRAY_TEST_BINARY"), "set XRAY_TEST_BINARY for real core config checks")
    def test_official_shared_core_rejects_invalid_protocol(self):
        binary = str(Path(os.environ["XRAY_TEST_BINARY"]).resolve())
        with tempfile.TemporaryDirectory(prefix="shared-xray-invalid-") as temporary:
            path = Path(temporary) / "invalid.json"
            result = check_core_config(binary, {"outbounds": [{"protocol": "invalid-validation-control"}]}, path)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unknown config id: invalid-validation-control", result.stdout + result.stderr)

    @unittest.skipUnless(os.environ.get("XRAY_TEST_BINARY"), "set XRAY_TEST_BINARY for real core config checks")
    def test_official_shared_core_accepts_all_generated_configs(self):
        binary = str(Path(os.environ["XRAY_TEST_BINARY"]).resolve())
        version = subprocess.run([binary, "version"], capture_output=True, text=True, timeout=15)
        self.assertEqual(version.returncode, 0, version.stdout + version.stderr)
        self.assertRegex(version.stdout, r"^Xray " + re.escape(TARGET_VERSION) + r"\b")
        with tempfile.TemporaryDirectory(prefix="shared-xray-config-") as temporary:
            for index, (label, config) in enumerate(generated_configs().items()):
                with self.subTest(config=label):
                    path = Path(temporary) / (str(index) + ".json")
                    result = check_core_config(binary, config, path)
                    self.assertEqual(result.returncode, 0, label + "\n" + result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
