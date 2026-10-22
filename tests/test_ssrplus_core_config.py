#!/usr/bin/env python3
"""Execute real subscription Lua through the real final core JSON generator.

Only OS, UCI, JSON and nixio bindings are substituted. Both complete upstream
programs and the packaged lua-neturl execute in Lua 5.1. No network, installed
core, native UCI configuration or router is accessed.
"""
import base64
import copy
import hashlib
import json
from pathlib import Path
import unittest
from urllib.parse import quote

import test_ssrplus_subscription as subscription_tests


ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "tests/fixtures/ssrplus/2abdc9aa/gen_config.lua"
GENERATOR_SHA256 = "58784f09dece11bd755acc99e14bac05a0d87c5dacce01aa72ca82a801a93f21"
GENERATOR_GIT_BLOB = "e226697bced19dab2481fd920f3cad219fa0c666"
USERS = {"ss": "YWVzLTEyOC1nY206c2VjcmV0",
         "vless": "12345678-1234-1234-1234-123456789abc", "trojan": "secret"}
CORE_BINARIES = {"xray", "sslocal", "ss-redir", "trojan"}


def link(protocol, query):
    return protocol + "://" + USERS[protocol] + "@ss.example:443?" + query + "#Transport"


def lua_to_python(value):
    if hasattr(value, "items"):
        result = {key: lua_to_python(item) for key, item in value.items()}
        if result and set(result) == set(range(1, len(result) + 1)):
            return [result[key] for key in range(1, len(result) + 1)]
        return result
    return value


def generate_core_config(node, installed_cores=CORE_BINARIES):
    """Run unmodified gen_config.lua with a committed subscriber node."""
    source_bytes = GENERATOR.read_bytes()
    if hashlib.sha256(source_bytes).hexdigest() != GENERATOR_SHA256:
        raise AssertionError("unmodified public gen_config.lua SHA-256 changed")
    blob = b"blob " + str(len(source_bytes)).encode() + b"\0" + source_bytes
    if hashlib.sha1(blob).hexdigest() != GENERATOR_GIT_BLOB:
        raise AssertionError("unmodified public gen_config.lua Git blob changed")
    lua = subscription_tests.LuaRuntime(unpack_returned_tuples=True)
    globals_ = lua.globals()
    output = []

    def lua_value(value):
        return lua.table_from(value, recursive=True) if isinstance(value, (dict, list)) else value

    def get_all(config, section):
        if config != "shadowsocksr":
            raise AssertionError("unexpected generator UCI config: " + config)
        sections = {"candidate": copy.deepcopy(node), "@socks5_proxy[0]": {},
                    "@global_xray_fragment[0]": {"fragment": "0", "noise": "0"},
                    "@xray_noise_packets[0]": {"enabled": "0"}}
        if section not in sections:
            raise AssertionError("unexpected generator UCI section: " + section)
        return lua_value(sections[section])

    def exec_command(command):
        if command == 'type -t -p "xray" 2>/dev/null':
            return "/usr/bin/xray\n" if "xray" in installed_cores else ""
        if command == "xray version 2>&1" and "xray" in installed_cores:
            return "Xray 26.9.1\n"
        raise AssertionError("unexpected generator command: " + command)

    def decode(value):
        try:
            return base64.b64decode(value + "=" * (-len(value) % 4), validate=True).decode()
        except (ValueError, UnicodeDecodeError):
            return None

    def parse_json(value):
        try:
            return lua_value(json.loads(value))
        except (TypeError, ValueError):
            return None

    globals_.py_get_all = get_all
    globals_.py_exec = exec_command
    globals_.py_b64decode = decode
    globals_.py_b64encode = lambda value: base64.b64encode(value.encode()).decode()
    globals_.py_json_parse = parse_json
    globals_.py_json_stringify = lambda value, *args: json.dumps(lua_to_python(value))
    globals_.py_output = lambda value: output.append(json.loads(value))
    # Match init.d gen_config dispatch: native SS argv[4] is a protocol,
    # while Xray argv[4] is the additional SOCKS listener port.
    fourth_argument = "redir" if node.get("type") in {"ss", "ss-rust", "ss-libev"} else "1080"
    globals_.arg = lua_value(["candidate", "tcp", "1234", fourth_argument])
    lua.execute(r'''
luci = {sys={exec=function(command) return py_exec(command) end}}
nixio = {bin={b64decode=function(value) return py_b64decode(value) end,
              b64encode=function(value) return py_b64encode(value) end}}
package.preload["luci.sys"] = function() return luci.sys end
package.preload["luci.model.uci"] = function()
    return {cursor=function()
        return {get_all=function(self, ...) return py_get_all(...) end}
    end}
end
package.preload["luci.cbi.datatypes"] = function()
    return {hostname=function(value) return value == "ss.example" end}
end
package.preload["luci.jsonc"] = function()
    return {parse=function(value) return py_json_parse(value) end,
            stringify=function(...) return py_json_stringify(...) end}
end
print = function(value) py_output(value) end
''')
    lua.execute(source_bytes.decode("utf-8").split("\n", 1)[1])
    if len(output) != 1:
        raise AssertionError("generator did not emit exactly one JSON configuration")
    return output[0]


@unittest.skipUnless(subscription_tests.LuaRuntime, "optional lupa.lua51 is required")
class SubscriptionCoreConfigRegressions(unittest.TestCase):
    def setUp(self):
        # Composition keeps unittest from discovering the 41 subscriber tests again.
        self.subscriber = subscription_tests.SubscriptionRegressions()
        self.subscriber.setUp()
        self.addCleanup(self.subscriber.doCleanups)

    def subscribe(self, uri, ss_type="v2ray", cores=CORE_BINARIES):
        subscriber = self.subscriber
        subscriber.sections["subscribe"]["ss_type"] = ss_type
        subscriber.sections["subscribe"]["xray_tj_type"] = "v2ray"
        subscriber.installed_cores = set(cores)
        subscriber.downloads[subscription_tests.URL_A] = base64.b64encode(uri.encode()).decode()
        subscriber.files.pop("/tmp/sub_md5_" + subscription_tests.group_hash(subscription_tests.URL_A), None)
        self.assertEqual(subscriber.run_subscriber(), 0, subscriber.logs)
        node = next(node for node in subscriber.persisted.values()
                    if node.get("grouphashkey") == subscription_tests.group_hash(subscription_tests.URL_A))
        return node, generate_core_config(node, set(cores))

    def stream(self, uri):
        node, config = self.subscribe(uri)
        self.assertEqual(node["type"], "v2ray")
        return config["outbounds"][0]["streamSettings"]

    def test_trojan_grpc_service_name_reaches_core_without_second_decode(self):
        stream = self.stream(link("trojan", "type=grpc&serviceName=svc%252F%2B&mode=multi"))
        self.assertEqual(stream["grpcSettings"].get("serviceName"), "svc%2F+")
        self.assertTrue(stream["grpcSettings"]["multiMode"])

    def test_trojan_http_header_type_reaches_core(self):
        stream = self.stream(link("trojan", "type=tcp&headerType=http&host=cdn.example&path=%2Fproxy"))
        raw = stream.get("rawSettings", {})
        self.assertEqual(raw.get("header", {}).get("type"), "http")
        self.assertEqual(raw["header"]["request"]["path"], ["/proxy"])
        self.assertEqual(raw["header"]["request"]["headers"]["Host"], ["cdn.example"])

    def test_ss_vless_http_host_and_path_reach_core(self):
        for protocol in ("ss", "vless"):
            with self.subTest(protocol=protocol):
                stream = self.stream(link(protocol, "type=tcp&headerType=http&host=cdn.example&path=%2Fa%252Fb%2Bc+d"))
                request = stream["rawSettings"]["header"]["request"]
                self.assertEqual(request["path"], ["/a%2Fb+c d"])
                self.assertEqual(request.get("headers", {}).get("Host"), ["cdn.example"])

    def test_tcp_http_host_only_and_empty_path_keep_default_request(self):
        for protocol in ("ss", "vless", "trojan"):
            for path in ("", "&path="):
                with self.subTest(protocol=protocol, path=path):
                    stream = self.stream(link(protocol, "type=tcp&headerType=http&host=cdn.example" + path))
                    request = stream.get("rawSettings", {}).get("header", {}).get("request", {})
                    self.assertEqual(request.get("path"), ["/"])
                    self.assertEqual(request.get("headers", {}).get("Host"), ["cdn.example"])

    def test_tcp_http_path_only_reaches_core(self):
        for protocol in ("ss", "vless", "trojan"):
            with self.subTest(protocol=protocol):
                stream = self.stream(link(protocol, "type=tcp&headerType=http&path=%2Fproxy"))
                request = stream.get("rawSettings", {}).get("header", {}).get("request", {})
                self.assertEqual(request.get("path"), ["/proxy"])
                self.assertNotIn("Host", request.get("headers", {}))

    def test_trojan_kcp_and_quic_case_insensitive_keys_preserve_values(self):
        kcp = self.stream(link("trojan", "TYPE=kcp&HEADERTYPE=dns&HOST=Dns.Example&SEED=MiXeD%2B%252F"))
        self.assertEqual(kcp["finalmask"]["udp"], [
            {"type": "header-dns", "settings": {"domain": "Dns.Example"}},
            {"type": "mkcp-aes128gcm", "settings": {"password": "MiXeD+%2F"}}])
        quic = self.stream(link("trojan", "TYPE=quic&HEADERTYPE=srtp&QUICSECURITY=aes-128-gcm&KEY=MiXeD%2B%252F"))
        self.assertEqual(quic["quicSettings"]["header"]["type"], "srtp")
        self.assertEqual(quic["quicSettings"].get("security"), "aes-128-gcm")
        self.assertEqual(quic["quicSettings"].get("key"), "MiXeD+%2F")

    def test_finalmask_json_reaches_core_for_all_three_protocols(self):
        encoded = quote('{"tcp":[{"type":"fragment","settings":{"packets":"tlshello","length":"100-200","interval":"10-20"}}]}', safe="")
        want = {"tcp": [{"type": "fragment", "settings": {"packets": "tlshello", "length": "100-200", "interval": "10-20"}}]}
        for protocol in ("ss", "trojan", "vless"):
            with self.subTest(protocol=protocol):
                stream = self.stream(link(protocol, "type=raw&fm=" + encoded))
                self.assertEqual(stream.get("finalmask"), want)

    def test_native_ss_credentials_keep_standard_base64_plus(self):
        authorities = ("YWVzLTEyOC1nY206fn5+@ss.example:443",
                       "YWVzLTEyOC1nY206fn5%2B@ss.example:443",
                       "YWVzLTEyOC1nY206fn5-@ss.example:443",
                       "YWVzLTEyOC1nY206fn5+QHNzLmV4YW1wbGU6NDQz")
        for preference in ("ss-rust", "ss-libev"):
            for authority in authorities:
                with self.subTest(preference=preference, authority=authority):
                    node, config = self.subscribe("ss://" + authority + "#Plus", preference)
                    self.assertEqual(node["type"], preference)
                    self.assertEqual(config["password"], "~~~")
                    self.assertEqual(config["protocol"], "redir")
                    self.assertEqual(config["method"], "aes-128-gcm")
                    self.assertEqual(config["server"], "ss.example")

    def test_native_ss_plus_fix_keeps_libev_only_and_rust_only_selection(self):
        for preference, cores in (("ss-libev", {"ss-redir"}), ("ss-rust", {"sslocal"})):
            with self.subTest(preference=preference):
                node, config = self.subscribe("ss://YWVzLTEyOC1nY206fn5+@ss.example:443#Plus", preference, cores)
                self.assertEqual(node["type"], preference)
                self.assertEqual(config["password"], "~~~")
                self.assertEqual(config["protocol"], "redir")

    def test_tls_transport_host_stays_distinct_from_sni(self):
        for protocol in ("ss", "vless", "trojan"):
            for transport, settings in (("ws", "wsSettings"), ("httpupgrade", "httpupgradeSettings")):
                with self.subTest(protocol=protocol, transport=transport):
                    stream = self.stream(link(protocol, "type=" + transport + "&security=tls&host=cdn.example&sni=tls.example&path=%2Fa%252Fb%2B"))
                    self.assertEqual(stream[settings]["host"], "cdn.example")
                    self.assertEqual(stream[settings]["path"], "/a%2Fb+")
                    self.assertEqual(stream["tlsSettings"]["serverName"], "tls.example")

    def test_tls_empty_or_absent_host_falls_back_to_sni(self):
        for protocol in ("ss", "vless", "trojan"):
            for transport, settings in (("ws", "wsSettings"), ("httpupgrade", "httpupgradeSettings")):
                for host in ("", "&host="):
                    with self.subTest(protocol=protocol, transport=transport, host=host):
                        stream = self.stream(link(protocol, "type=" + transport + "&security=tls&sni=tls.example" + host))
                        self.assertEqual(stream[settings]["host"], "tls.example")

    def test_tls_missing_host_and_sni_keeps_default_path(self):
        for protocol in ("ss", "vless", "trojan"):
            for transport, settings in (("ws", "wsSettings"), ("httpupgrade", "httpupgradeSettings")):
                with self.subTest(protocol=protocol, transport=transport):
                    stream = self.stream(link(protocol, "type=" + transport + "&security=tls"))
                    self.assertNotIn("host", stream[settings])
                    self.assertEqual(stream[settings]["path"], "/")

    def test_reality_transport_host_is_independent_and_spiderx_decodes_once(self):
        for protocol in ("ss", "vless"):
            for transport, settings in (("ws", "wsSettings"), ("httpupgrade", "httpupgradeSettings")):
                with self.subTest(protocol=protocol, transport=transport):
                    stream = self.stream(link(protocol, "type=" + transport + "&security=reality&host=cdn.example&sni=tls.example&pbk=publickey&sid=abcd&spx=%2F%252F%2B"))
                    self.assertEqual(stream[settings]["host"], "cdn.example")
                    self.assertEqual(stream["realitySettings"]["serverName"], "tls.example")
                    self.assertEqual(stream["realitySettings"]["spiderX"], "/%2F+")

    def test_vmess_existing_independent_tls_host_is_preserved(self):
        uri = "vmess://" + base64.b64encode(json.dumps({
            "v": "2", "ps": "VMess", "add": "ss.example", "port": "443",
            "id": "12345678-1234-1234-1234-123456789abc", "aid": "0",
            "net": "ws", "type": "none", "host": "cdn.example", "path": "/proxy",
            "tls": "tls", "sni": "tls.example"}).encode()).decode()
        stream = self.stream(uri)
        self.assertEqual(stream["wsSettings"]["host"], "cdn.example")
        self.assertEqual(stream["tlsSettings"]["serverName"], "tls.example")

    def test_malformed_finalmask_is_not_emitted_as_core_configuration(self):
        for protocol in ("ss", "vless", "trojan"):
            with self.subTest(protocol=protocol):
                stream = self.stream(link(protocol, "type=raw&fm=%7Bbad-json"))
                self.assertNotIn("finalmask", stream)

    def test_invalid_transport_parameter_preserves_old_group_and_manual_node(self):
        subscriber = self.subscriber
        old = copy.deepcopy(subscriber.persisted)
        subscriber.sections["subscribe"]["ss_type"] = "v2ray"
        subscriber.installed_cores = CORE_BINARIES
        subscriber.downloads[subscription_tests.URL_A] = base64.b64encode(link("ss", "type=ws&host[bad]=cdn.example&security=tls").encode()).decode()
        self.assertNotEqual(subscriber.run_subscriber(), 0)
        for section in ("old_a", "manual"):
            self.assertEqual(subscriber.persisted[section], old[section])
        self.assertEqual(subscriber.persisted["global"], old["global"])
        self.assertNotIn("/tmp/sub_md5_" + subscription_tests.group_hash(subscription_tests.URL_A), subscriber.files)


if __name__ == "__main__":
    unittest.main()
