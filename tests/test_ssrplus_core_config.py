#!/usr/bin/env python3
# Historical 190-r12 regression only; production v198.2 coverage is test_ssrplus_v198.py.
"""Execute real subscription Lua through the real final core JSON generator.

Only OS, UCI, JSON and nixio bindings are substituted. Both complete repaired
programs and the packaged lua-neturl execute in Lua 5.1. No network, installed
core, native UCI configuration or router is accessed.
"""
import base64
import copy
import hashlib
import json
from functools import lru_cache
from pathlib import Path
import subprocess
import tempfile
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


@lru_cache(maxsize=1)
def generator_source():
    """Protect the public input, then apply the real generator repair artifact."""
    source_bytes = GENERATOR.read_bytes()
    if hashlib.sha256(source_bytes).hexdigest() != GENERATOR_SHA256:
        raise AssertionError("unmodified public gen_config.lua SHA-256 changed")
    blob = b"blob " + str(len(source_bytes)).encode() + b"\0" + source_bytes
    if hashlib.sha1(blob).hexdigest() != GENERATOR_GIT_BLOB:
        raise AssertionError("unmodified public gen_config.lua Git blob changed")
    patch = ROOT / "tests/fixtures/ssrplus-legacy/wrt_core/patches/ssrplus-core-transport.patch"
    if not patch.exists():
        return source_bytes
    with tempfile.TemporaryDirectory(prefix="ssr-core-source-") as temporary:
        target = Path(temporary) / "root/usr/share/shadowsocksr/gen_config.lua"
        target.parent.mkdir(parents=True)
        target.write_bytes(source_bytes)
        result = subprocess.run(["git", "-C", temporary, "init", "-q"],
                                capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise AssertionError(result.stderr)
        result = subprocess.run(["git", "-C", temporary, "apply",
            "--include=root/usr/share/shadowsocksr/gen_config.lua", str(patch)],
            capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise AssertionError(result.stderr)
        return target.read_bytes()


def link(protocol, query):
    return protocol + "://" + USERS[protocol] + "@ss.example:443?" + query + "#Transport"


def lua_to_python(value):
    if hasattr(value, "items"):
        result = {key: lua_to_python(item) for key, item in value.items()}
        if result and set(result) == set(range(1, len(result) + 1)):
            return [result[key] for key in range(1, len(result) + 1)]
        return result
    return value


def generate_core_config(node, installed_cores=CORE_BINARIES, *, runtime_args=None,
                         section_name="candidate", uci_sections=None, xray_version="26.9.1"):
    """Run the complete repaired generator with a committed subscriber node."""
    source_bytes = generator_source()
    lua = subscription_tests.LuaRuntime(unpack_returned_tuples=True)
    globals_ = lua.globals()
    output = []

    def lua_value(value):
        return lua.table_from(value, recursive=True) if isinstance(value, (dict, list)) else value

    def get_all(config, section):
        if config != "shadowsocksr":
            raise AssertionError("unexpected generator UCI config: " + config)
        sections = {section_name: copy.deepcopy(node), "@socks5_proxy[0]": {},
                    "@global_xray_fragment[0]": {"fragment": "0", "noise": "0"},
                    "@xray_noise_packets[0]": {"enabled": "0"}}
        if uci_sections is not None:
            sections[section_name] = copy.deepcopy(uci_sections[section_name])
            for kind in ("socks5_proxy", "global_xray_fragment", "xray_noise_packets"):
                sections["@" + kind + "[0]"] = next(
                    (copy.deepcopy(value) for value in uci_sections.values()
                     if value.get(".type") == kind), sections["@" + kind + "[0]"])
        if section not in sections:
            raise AssertionError("unexpected generator UCI section: " + section)
        return lua_value(sections[section])

    def exec_command(command):
        if command == 'type -t -p "xray" 2>/dev/null':
            return "/usr/bin/xray\n" if "xray" in installed_cores else ""
        if command == "xray version 2>&1" and "xray" in installed_cores:
            return "Xray " + xray_version + "\n"
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
    globals_.arg = lua_value([section_name, *(runtime_args or ["tcp", "1234", fourth_argument])])
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
        self.reset_subscriber()

    def reset_subscriber(self):
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

    def seed_legacy_native_selection(self, preference, entries=None):
        """Parse actual native subscription links with the pre-r10 parser."""
        self.reset_subscriber()
        subscriber = self.subscriber
        current_source = subscriber.source
        subscriber.source = subscription_tests.subscription_source(
            exclude_patches=("ssrplus-ss-password.patch", "ssrplus-node-references.patch",
                             "ssrplus-core-transport.patch"))
        unrelated = {sid: copy.deepcopy(subscriber.sections[sid]) for sid in ("old_b", "manual")}
        subscriber.sections = {sid: value for sid, value in subscriber.sections.items()
                               if sid in ("global", "subscribe")}
        subscriber.sections["global"]["global_server"] = "nil"
        subscriber.sections["subscribe"]["ss_type"] = preference
        subscriber.installed_cores = {"sslocal", "ss-redir"}
        links = []
        for password, alias, host in (entries or (("ordinary", "First", "first.example"),
                                                  ("%2F", "Percent", "ss.example"))):
            credentials = base64.b64encode(("aes-128-gcm:" + password).encode()).decode()
            links.append("ss://" + credentials + "@" + host + ":443#" + alias)
        subscriber.downloads[subscription_tests.URL_A] = base64.b64encode("\n".join(links).encode()).decode()
        subscriber.files.pop("/tmp/sub_md5_" + subscription_tests.group_hash(subscription_tests.URL_A), None)
        self.assertEqual(subscriber.run_subscriber(), 0, subscriber.logs)
        selected_alias = entries[1][1] if entries else "Percent"
        old_sid, old_node = next((sid, node) for sid, node in subscriber.persisted.items()
                                 if node.get("alias") == selected_alias)
        first_sid = next(sid for sid, node in subscriber.persisted.items() if node.get("alias") == "First")
        self.assertNotEqual(old_sid, first_sid)
        self.assertEqual(old_node["password"], "/")
        subscriber.sections.update(unrelated)
        subscriber.sections["global"].update(global_server=old_sid, udp_relay_server=old_sid,
                                             netflix_server=old_sid, netflix_enable="1")
        subscriber.sections["socks"] = {".type": "socks5_proxy", "server": old_sid,
                                       "enabled": "1", "local_port": "1080"}
        subscriber.source = current_source
        subscriber.events.clear()
        subscriber.logs.clear()
        return old_sid

    def assert_selected_native_configs(self, state, expected_password="%2F"):
        # These are the native init.d dispatch arguments, including UDP mode
        # and the SOCKS-specific fourth argument, for each committed reference.
        references = (("global", "global_server", ["tcp", "1234", "redir"], "tcp_only"),
                      ("global", "udp_relay_server", ["udp", "1235", "redir"], "udp_only"),
                      ("global", "netflix_server", ["tcp", "1236", "redir"], "tcp_only"),
                      ("socks", "server", ["tcp", "1080", "socks"], "tcp_only"))
        for owner, key, arguments, mode in references:
            with self.subTest(reference=owner + "." + key):
                sid = state[owner][key]
                self.assertIn(sid, state, "selected reference points to a deleted node")
                self.assertEqual(state[sid]["alias"], "Percent")
                config = generate_core_config(state[sid], self.subscriber.installed_cores,
                                              runtime_args=arguments, section_name=sid,
                                              uci_sections=state)
                self.assertEqual(config["password"], expected_password)
                self.assertEqual(config["server"], "ss.example")
                self.assertEqual(config["server_port"], 443)
                self.assertEqual(config["method"], "aes-128-gcm")
                self.assertEqual(config["protocol"], arguments[2])
                self.assertEqual(config["mode"], mode)
                self.assertEqual(config["local_port"], int(arguments[1]))

    def test_native_password_reparse_preserves_each_actual_selected_core_before_restart(self):
        for preference in ("ss-rust", "ss-libev"):
            with self.subTest(preference=preference):
                self.seed_legacy_native_selection(preference)
                subscriber = self.subscriber
                before = copy.deepcopy(subscriber.sections)
                self.assertEqual(subscriber.run_subscriber(), 0, subscriber.logs)
                self.assertEqual(subscriber.persisted, before, "MD5 hit changed selected configuration")
                self.assertFalse([event for event in subscriber.events if event[0] in ("commit", "service")])
                subscriber.files.pop("/tmp/sub_md5_" + subscription_tests.group_hash(subscription_tests.URL_A))
                subscriber.events.clear()
                observed = []
                subscriber.service_callback = lambda: observed.append(copy.deepcopy(subscriber.persisted))
                self.assertEqual(subscriber.run_subscriber(), 0, subscriber.logs)
                self.assertEqual(observed, [subscriber.persisted], "restart did not observe committed configuration")
                lifecycle = [event for event in subscriber.events if event[0] in ("commit", "service")]
                self.assertEqual([event[0] for event in lifecycle], ["commit", "service"])
                self.assertEqual(lifecycle[1][1], "restart")
                self.assertTrue(lifecycle[1][3])
                self.assert_selected_native_configs(observed[0])
                merged_sid = observed[0]["global"]["global_server"]
                for protocol in ("redir", "socks"):
                    config = generate_core_config(observed[0][merged_sid], subscriber.installed_cores,
                                                  runtime_args=["tcp,udp", "1234", protocol],
                                                  section_name=merged_sid, uci_sections=observed[0])
                    self.assertEqual(config["password"], "%2F")
                    self.assertEqual(config["mode"], "tcp_and_udp")
                    self.assertEqual(config["protocol"], protocol)
                for sid in ("manual", "old_b"):
                    self.assertEqual(subscriber.persisted[sid], before[sid])

    def test_distinct_native_selections_keep_each_reference_endpoint_and_core_credentials(self):
        entries = (("ordinary", "First", "first.example"), ("%2F", "Main", "main.example"),
                   ("%252F", "UDP", "udp.example"), ("%2B", "SOCKS", "socks.example"),
                   ("%3A", "Netflix", "netflix.example"))
        routes = (("global", "global_server", "Main", "%2F", "/", "main.example", ["tcp", "1234", "redir"]),
                  ("global", "udp_relay_server", "UDP", "%252F", "%2F", "udp.example", ["udp", "1235", "redir"]),
                  ("global", "netflix_server", "Netflix", "%3A", ":", "netflix.example", ["tcp", "1236", "redir"]),
                  ("socks", "server", "SOCKS", "%2B", "+", "socks.example", ["tcp", "1080", "socks"]))
        for preference in ("ss-rust", "ss-libev"):
            with self.subTest(preference=preference):
                self.seed_legacy_native_selection(preference, entries)
                subscriber = self.subscriber
                ids = {node["alias"]: sid for sid, node in subscriber.sections.items() if node.get(".type") == "servers"}
                for owner, key, alias, password, old_password, host, arguments in routes:
                    subscriber.sections[owner][key] = ids[alias]
                    self.assertEqual(subscriber.sections[ids[alias]]["password"], old_password)
                before = copy.deepcopy(subscriber.sections)
                subscriber.files.pop("/tmp/sub_md5_" + subscription_tests.group_hash(subscription_tests.URL_A))
                observed = []
                subscriber.service_callback = lambda: observed.append(copy.deepcopy(subscriber.persisted))
                self.assertEqual(subscriber.run_subscriber(), 0, subscriber.logs)
                self.assertEqual(observed, [subscriber.persisted])
                for owner, key, alias, password, old_password, host, arguments in routes:
                    with self.subTest(reference=owner + "." + key):
                        sid = observed[0][owner][key]
                        self.assertEqual(sid, before[owner][key])
                        self.assertIn(sid, observed[0], "selected reference points to a deleted node")
                        self.assertEqual(observed[0][sid]["alias"], alias)
                        config = generate_core_config(observed[0][sid], subscriber.installed_cores,
                                                      runtime_args=arguments, section_name=sid,
                                                      uci_sections=observed[0])
                        self.assertEqual(config["server"], host)
                        self.assertEqual(config["password"], password)
                        self.assertEqual(config["protocol"], arguments[2])
                        self.assertEqual(config["mode"], arguments[0] + "_only")
                lifecycle = [event[0] for event in subscriber.events if event[0] in ("commit", "service")]
                self.assertEqual(lifecycle, ["commit", "service"])

    def test_native_password_migration_keeps_manual_other_group_and_disabled_choices(self):
        choices = (("manual", "old_b", "nil", "same", "0", "0"),
                   ("nil", "same", "old_b", "manual", "1", "1"),
                   ("old_b", "nil", "same", "nil", "1", "1"))
        for preference in ("ss-rust", "ss-libev"):
            for main, udp, netflix, socks, netflix_enabled, socks_enabled in choices:
                with self.subTest(preference=preference, choices=(main, udp, netflix, socks)):
                    old_sid = self.seed_legacy_native_selection(preference)
                    subscriber = self.subscriber
                    subscriber.sections["global"].update(global_server=main, udp_relay_server=udp,
                                                         netflix_server=netflix, netflix_enable=netflix_enabled)
                    subscriber.sections["socks"].update(server=socks, enabled=socks_enabled)
                    before = copy.deepcopy(subscriber.sections)
                    subscriber.files.pop("/tmp/sub_md5_" + subscription_tests.group_hash(subscription_tests.URL_A))
                    self.assertEqual(subscriber.run_subscriber(), 0, subscriber.logs)
                    for sid in ("global", "socks", "manual", "old_b"):
                        self.assertEqual(subscriber.persisted[sid], before[sid])
                    self.assertIn(old_sid, subscriber.persisted)
                    self.assertEqual(subscriber.persisted[old_sid]["password"], "%2F")

    def test_failed_subscription_keeps_all_selected_core_references_while_other_group_updates(self):
        for preference in ("ss-rust", "ss-libev"):
            with self.subTest(preference=preference):
                self.seed_legacy_native_selection(preference)
                subscriber = self.subscriber
                subscriber.sections["subscribe"]["subscribe_url"] = [subscription_tests.URL_A,
                                                                      subscription_tests.URL_B]
                subscriber.http_codes[subscription_tests.URL_A] = 503
                before = copy.deepcopy(subscriber.sections)
                marker = "/tmp/sub_md5_" + subscription_tests.group_hash(subscription_tests.URL_A)
                old_md5 = subscriber.files[marker]
                self.assertNotEqual(subscriber.run_subscriber(), 0, subscriber.logs)
                for sid, node in before.items():
                    if sid in ("global", "socks", "manual") or node.get("grouphashkey") == subscription_tests.group_hash(subscription_tests.URL_A):
                        self.assertEqual(subscriber.persisted[sid], node)
                self.assert_selected_native_configs(subscriber.persisted, expected_password="/")
                self.assertTrue(any(node.get("server") == "new-b.example" for node in subscriber.persisted.values()))
                self.assertEqual(subscriber.files[marker], old_md5)
                subscriber.http_codes.clear()

    def test_native_percent_literals_with_invalid_legacy_utf8_reach_selected_core(self):
        for preference in ("ss-rust", "ss-libev"):
            for password in ("%FF", "%ED%A0%80"):
                with self.subTest(preference=preference, password=password):
                    self.seed_legacy_native_selection(preference)
                    subscriber = self.subscriber
                    # A newly published node has valid literal ASCII credentials;
                    # an optional r9 identity probe must not decode them into bad UTF-8.
                    credentials = base64.b64encode(("aes-128-gcm:" + password).encode()).decode()
                    subscriber.downloads[subscription_tests.URL_A] = base64.b64encode(
                        ("ss://" + credentials + "@ss.example:443#Published").encode()).decode()
                    subscriber.sections["global"].update(global_server="nil", udp_relay_server="nil",
                                                         netflix_server="nil", netflix_enable="0")
                    subscriber.sections["socks"].update(server="nil", enabled="0")
                    self.assertEqual(subscriber.run_subscriber(), 0, subscriber.logs)
                    new_sid, node = next((sid, value) for sid, value in subscriber.persisted.items()
                                         if value.get("alias") == "Published")
                    # Select the actual committed node, then execute the complete
                    # unchanged generator with that real section identifier.
                    subscriber.sections["global"]["global_server"] = new_sid
                    subscriber.events.clear()
                    self.assertEqual(subscriber.run_subscriber(), 0, subscriber.logs)
                    self.assertEqual(subscriber.persisted["global"]["global_server"], new_sid)
                    config = generate_core_config(node, subscriber.installed_cores, section_name=new_sid,
                                                  uci_sections=subscriber.persisted)
                    self.assertEqual(config["password"], password)
                    self.assertEqual(config["server"], "ss.example")
                    self.assertFalse([event for event in subscriber.events if event[0] in ("commit", "service")])

    def test_native_ordinary_subscription_md5_hit_preserves_full_selected_state(self):
        for preference in ("ss-rust", "ss-libev"):
            with self.subTest(preference=preference):
                self.seed_legacy_native_selection(preference)
                subscriber = self.subscriber
                first_sid = next(sid for sid, node in subscriber.sections.items() if node.get("alias") == "First")
                subscriber.sections = {sid: node for sid, node in subscriber.sections.items()
                                       if node.get("alias") != "Percent"}
                first = subscriber.downloads[subscription_tests.URL_A]
                subscriber.downloads[subscription_tests.URL_A] = base64.b64encode(
                    base64.b64decode(first).decode().splitlines()[0].encode()).decode()
                subscriber.sections["global"].update(global_server=first_sid, udp_relay_server=first_sid,
                                                     netflix_server=first_sid)
                subscriber.sections["socks"]["server"] = first_sid
                self.assertEqual(subscriber.run_subscriber(), 0, subscriber.logs)
                before = copy.deepcopy(subscriber.persisted)
                subscriber.events.clear()
                self.assertEqual(subscriber.run_subscriber(), 0, subscriber.logs)
                self.assertEqual(subscriber.persisted, before)
                self.assertFalse([event for event in subscriber.events if event[0] in ("commit", "service")])

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

    def test_trojan_kcp_case_insensitive_keys_preserve_values(self):
        kcp = self.stream(link("trojan", "TYPE=kcp&HEADERTYPE=dns&HOST=Dns.Example&SEED=MiXeD%2B%252F"))
        self.assertEqual(kcp["finalmask"]["udp"], [
            {"type": "mkcp-legacy", "settings": {"header": "dns", "value": "Dns.Example"}},
            {"type": "mkcp-legacy", "settings": {"value": "MiXeD+%2F"}}])

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

    def test_native_ss_base64_password_percent_literals_reach_core_in_all_link_forms(self):
        # Base64 contains the exact credentials, not a URI-encoded password.
        # Only the surrounding Base64 text may have an outer URI-escape layer.
        password = "%2F%252F"
        for preference in ("ss-rust", "ss-libev"):
            for whole_link in (False, True):
                credentials = "aes-128-gcm:" + password
                payload = credentials + ("@ss.example:443" if whole_link else "")
                standard = base64.b64encode(payload.encode()).decode()
                forms = {"standard": standard,
                         "urlsafe": base64.urlsafe_b64encode(payload.encode()).decode().rstrip("="),
                         "outer-uri-escaped": quote(standard, safe="")}
                for form, encoded in forms.items():
                    with self.subTest(preference=preference, whole_link=whole_link, form=form):
                        authority = encoded + ("" if whole_link else "@ss.example:443")
                        node, config = self.subscribe("ss://" + authority + "#Percent", preference)
                        self.assertEqual(node["type"], preference)
                        self.assertEqual(config["password"], "%2F%252F")
                        self.assertEqual(node["password"], "%2F%252F")
                        self.assertEqual(config["method"], "aes-128-gcm")
                        self.assertEqual(config["server"], "ss.example")
                        self.assertEqual(config["server_port"], 443)
                        self.assertEqual(config["protocol"], "redir")

    def test_native_ss_base64_password_percent_patterns_and_real_slash_are_literal(self):
        passwords = ("%2F", "%252F", "%2f", "mixed+%2F%252F+", "bad%2G%2%", "real/slash+~~~")
        for preference in ("ss-rust", "ss-libev"):
            for password in passwords:
                with self.subTest(preference=preference, password=password):
                    encoded = base64.b64encode(("aes-128-gcm:" + password).encode()).decode()
                    node, config = self.subscribe("ss://" + encoded + "@ss.example:443#Literal", preference)
                    self.assertEqual(node["type"], preference)
                    self.assertEqual(config["password"], password)
                    self.assertEqual(node["password"], password)

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
