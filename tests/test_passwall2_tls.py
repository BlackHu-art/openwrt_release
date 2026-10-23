#!/usr/bin/env python3
"""Run the complete Passwall generators with isolated UCI/OS bindings.

--baseline runs the same assertions against the unpatched source to demonstrate
the original failure. Normal runs always apply the production repair helper.
"""
import base64
import copy
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from lupa.lua51 import LuaError, LuaRuntime


ROOT = Path(__file__).resolve().parents[1]
BASELINE = "--baseline" in sys.argv
if BASELINE:
    sys.argv.remove("--baseline")
PLUGINS = ("passwall2",)
PIN_HEX = "0123456789abcdef" * 4
PIN_BASE64 = "ASNFZ4mrze8BI0VniavN7wEjRWeJq83vASNFZ4mrze8="


def bash_path(path):
    path = Path(path).resolve().as_posix()
    return "/" + path[0].lower() + path[2:] if os.name == "nt" else path


def bash_executable():
    return shutil.which("bash") or r"C:\Program Files\Git\bin\bash.exe"


def function_source(source, name):
    match = re.search(r"(?ms)^function " + re.escape(name) + r"\(.*?^end\b", source)
    if not match:
        raise AssertionError("upstream helper missing: " + name)
    return match.group()


def as_python(value):
    if hasattr(value, "items"):
        result = {key: as_python(item) for key, item in value.items()}
        if result and set(result) == set(range(1, len(result) + 1)):
            return [result[i] for i in range(1, len(result) + 1)]
        return result
    return value


def generate(source, api_source, version, changes, *, full=True):
    # Latin-1 at the binding boundary preserves all 32 hash bytes. Source bytes
    # are still loaded unchanged as UTF-8, just as on the router.
    lua = LuaRuntime(unpack_returned_tuples=True, encoding="latin-1")
    globals_ = lua.globals()
    globals_.core_version = version
    globals_.py_encode = lambda value: base64.b64encode(value.encode("latin-1")).decode()

    def decode(value):
        try:
            return base64.b64decode(value, validate=True).decode("latin-1")
        except ValueError:
            return None

    globals_.py_decode = decode
    lua.execute(b'''
module = function() end
arg = {}
nixio = {bin={b64encode=py_encode,b64decode=py_decode}}
util = {split=function(value)
    local parts = {}; for part in value:gmatch("[^%.%-]+") do parts[#parts+1] = part end
    return parts
end}
api = {
    CACHE_PATH="/tmp/test", TMP_PATH="/tmp/test",
    get_app_version=function(name) assert(name == "sing-box"); return core_version end,
    jsonc={stringify=function(value) return value end},
    sys={call=function() error("unexpected shell operation") end},
    fs={readfile=function() return nil end},
    datatypes={hostname=function() return false end},
    clone=function(value) return value end,
    uci_get_c=function(id, option)
        if id == "fixture" then return option and fixture_node[option] or fixture_node end
    end,
    uci_foreach_c=function() end,
    cacheFileCompareToLogic=function() return true end
}
require = function(name)
    assert(name:match("^luci%.passwall2?%.api$"), name)
    return api
end
''')
    for name in ("base64Decode", "base64Encode", "sha256_xray_sb", "compare_versions", "split"):
        lua.execute(function_source(api_source, name).encode("utf-8"))
        globals_.api[name] = globals_[name]
    lua.execute(source)
    node = {".type": "nodes", ".name": "fixture", "type": "sing-box", "protocol": "trojan",
            "address": "192.0.2.1", "port": "443", "password": "secret-not-for-logs",
            "tls": "1", "tls_allowInsecure": "0", "tls_serverName": "example.com"}
    node.update(copy.deepcopy(changes))
    globals_.fixture_node = lua.table_from(node)
    if full:
        value = globals_.gen_config(lua.table_from({"flag": "fixture", "node": "fixture",
            "local_socks_address": "127.0.0.1", "local_socks_port": "12346", "no_run": "1"}))
    else:
        value = globals_.gen_outbound("fixture", globals_.fixture_node, "fixture", None)
    return as_python(value)


class PasswallTLSRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="passwall-tls-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.sources = {}
        for plugin in PLUGINS:
            original = ROOT / "maintenance/plugins" / plugin / ("luci-app-" + plugin)
            package = Path(cls.temp.name) / plugin
            for relative in (f"luasrc/{plugin}/util_sing-box.lua", f"root/usr/share/{plugin}/app.sh"):
                target = package / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(original / relative, target)
            subprocess.run(["git", "init", "-q", str(package)], check=True)
            if not BASELINE:
                env = dict(os.environ, BASE_PATH=bash_path(ROOT / "wrt_core"),
                           TEST_PACKAGE=bash_path(package), TEST_PLUGIN=plugin)
                result = subprocess.run([bash_executable(), "--noprofile", "--norc", "-c",
                    'source "$BASE_PATH/modules/plugin_compat.sh"; '
                    'fix_passwall2_compat "$TEST_PACKAGE"'],
                    env=env, capture_output=True, text=True)
                if result.returncode:
                    raise AssertionError(result.stdout + result.stderr)
            cls.sources[plugin] = ((package / f"luasrc/{plugin}/util_sing-box.lua").read_bytes(),
                                  (original / f"luasrc/{plugin}/api.lua").read_text(encoding="utf-8"))

    def generate(self, plugin, version="1.14.3", **changes):
        return generate(*self.sources[plugin], version, changes)

    def test_old_core_refuses_pin_even_with_explicit_insecure(self):
        for plugin in PLUGINS:
            for version in ("1.13.0", "1.14.3"):
                for insecure in ("0", "1"):
                    for pin in (PIN_HEX, PIN_BASE64, "malformed-pin"):
                        with self.subTest(plugin=plugin, version=version, insecure=insecure, pin=pin):
                            with self.assertRaisesRegex(LuaError, "certificate.*1[.]15") as caught:
                                self.generate(plugin, version, tls_pinSHA256=pin, tls_allowInsecure=insecure)
                            self.assertNotIn("secret-not-for-logs", str(caught.exception))
                            self.assertNotIn(pin, str(caught.exception))

    def test_protocols_with_implicit_tls_also_refuse_pin(self):
        for plugin in PLUGINS:
            for protocol in ("hysteria", "hysteria2", "tuic", "naive", "masque"):
                with self.subTest(plugin=plugin, protocol=protocol):
                    with self.assertRaisesRegex(LuaError, "certificate.*1[.]15"):
                        self.generate(plugin, protocol=protocol, tls="0", tls_pinSHA256=PIN_HEX)

    def test_no_pin_preserves_ca_verification_and_explicit_insecure(self):
        for plugin in PLUGINS:
            for version in ("1.14.3", "1.15.0"):
                for pin in (None, ""):
                    for insecure in ("0", "1"):
                        with self.subTest(plugin=plugin, version=version, pin=pin, insecure=insecure):
                            config = self.generate(plugin, version, tls_pinSHA256=pin, tls_allowInsecure=insecure)
                            tls = config["outbounds"][0]["tls"]
                            self.assertEqual(bool(tls.get("insecure")), insecure == "1")
                            self.assertNotIn("certificate_sha256", tls)
                            self.assertNotIn("certificate_public_key_sha256", tls)

    def test_supported_core_preserves_real_fingerprint_encoding(self):
        colon_hex = ":".join(PIN_HEX[i:i+2].upper() for i in range(0, 64, 2))
        for plugin in PLUGINS:
            for pin, expected in ((PIN_HEX, PIN_BASE64), (colon_hex, PIN_BASE64),
                                  (PIN_BASE64, PIN_BASE64), ("malformed-pin", "malformed-pin")):
                with self.subTest(plugin=plugin, pin=pin):
                    tls = self.generate(plugin, "1.15.0", tls_pinSHA256=pin)["outbounds"][0]["tls"]
                    self.assertFalse(tls["insecure"])
                    self.assertEqual(tls["certificate_sha256"], [expected])
                    self.assertNotIn("certificate_public_key_sha256", tls)

    def test_reality_without_pin_retains_its_authentication_options(self):
        for plugin in PLUGINS:
            with self.subTest(plugin=plugin):
                changes = {"protocol": "vless", "uuid": "12345678-1234-1234-1234-123456789abc",
                           "reality": "1", "reality_publicKey": "public-key", "reality_shortId": "abcd"}
                tls = self.generate(plugin, **changes)["outbounds"][0]["tls"]
                self.assertEqual(tls["reality"], {"enabled": True, "public_key": "public-key", "short_id": "abcd"})
                with self.assertRaisesRegex(LuaError, "certificate.*1[.]15"):
                    self.generate(plugin, **changes, tls_pinSHA256=PIN_HEX)

    def test_disabled_tls_does_not_reinterpret_a_saved_pin(self):
        for plugin in PLUGINS:
            with self.subTest(plugin=plugin):
                config = self.generate(plugin, protocol="socks", tls="0", tls_pinSHA256=PIN_HEX)
                self.assertNotIn("tls", config["outbounds"][0])


if __name__ == "__main__":
    unittest.main()
