#!/usr/bin/env python3
"""Check the production-patched DNS mapping, without claiming full ucode execution.

The DNS-settings assignment and DNS object are JavaScript-compatible ucode. Node
executes those actual source fragments with the production strToBool function.
Optional SING_BOX_TEST_BIN checks the resulting DNS JSON with the official core.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BASH = os.environ.get("BASH") or ("C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash"))
NODE = os.environ.get("NODE") or shutil.which("node")
CORE = os.environ.get("SING_BOX_TEST_BIN")


class HomeProxyDNSExpire(unittest.TestCase):
    def test_custom_dns_preserves_disabled_and_enabled_expiry_choices(self):
        self.assertTrue(NODE, "Node is required to execute the actual ucode fragments")
        fixture = ROOT / "tests/fixtures/homeproxy"
        library = (ROOT / "wrt_core/managed/packages/luci-app-homeproxy/root/etc/homeproxy/scripts/homeproxy.uc").read_text(encoding="utf-8")
        boolean = re.search(r"export (function strToBool\(str\) \{.*?\n\})", library, re.S).group(1)
        with tempfile.TemporaryDirectory(prefix="hp-dns-expire-") as temp:
            for layout in ("old", "fadaa676"):
                package = Path(temp) / layout
                generator = package / "root/etc/homeproxy/scripts/generate_client.uc"
                sources = {
                    "Makefile": "Makefile", "generate_client.uc": str(generator.relative_to(package)),
                    "client.js": "htdocs/luci-static/resources/view/homeproxy/client.js",
                    "homeproxy.init": "root/etc/init.d/homeproxy", "luci.homeproxy": "root/usr/share/rpcd/ucode/luci.homeproxy",
                }
                for source, target in sources.items():
                    origin = fixture / source
                    if layout == "fadaa676" and source in ("generate_client.uc", "client.js"):
                        origin = fixture / layout / source
                    destination = package / target
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(origin, destination)
                subprocess.run(["git", "init", "-q", str(package)], check=True, capture_output=True)
                subprocess.run(["git", "-C", str(package), "config", "core.autocrlf", "false"], check=True, capture_output=True)
                command = 'BASE_PATH="$1/wrt_core"; source "$BASE_PATH/modules/plugin_compat.sh"; source "$BASE_PATH/modules/feed_source_fixes.sh"; fix_homeproxy_compat "$2"'
                fixed = subprocess.run([BASH, "-c", command, "test", ROOT.as_posix(), package.as_posix()], capture_output=True, text=True, encoding="utf-8")
                self.assertEqual(fixed.returncode, 0, fixed.stdout + fixed.stderr)
                text = generator.read_text(encoding="utf-8")
                declaration = re.search(r"let main_node,.*?;", text, re.S).group(0)
                settings = re.search(r"/\* DNS settings \*/(.*?)/\* Routing settings \*/", text, re.S).group(1)
                dns = re.search(r"config\.dns = \{.*?\n\};", text, re.S).group(0)
                for value, expected in ((None, None), ("0", None), ("1", True)):
                    with self.subTest(layout=layout, value=value):
                        script = "const setting = " + json.dumps(value) + ";\n" + r'''
const uci = {get: (config, section, key) => key === 'disable_cache_expire' ? setting : null};
const uciconfig = 'homeproxy', ucidnssetting = 'dns', config = {}, wan_dns = '1.1.1.1', self_mark = false;
''' + boolean + "\n" + declaration + "\n" + settings + "\n" + dns + "\nconsole.log(JSON.stringify(config));"
                        result = subprocess.run([NODE, "-e", script], capture_output=True, text=True, encoding="utf-8")
                        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                        config = json.loads(result.stdout)
                        self.assertIn("disable_expire", config["dns"], "production patch dropped the UCI-to-DNS mapping")
                        self.assertEqual(config["dns"]["disable_expire"], expected)
                        if CORE:
                            # Production removeBlankAttrs omits null; the core default is false.
                            config["dns"] = {k: v for k, v in config["dns"].items() if v is not None}
                            for operation in ("format", "check"):
                                checked = subprocess.run([CORE, operation, "-c", "stdin"], input=json.dumps(config), capture_output=True, text=True, encoding="utf-8")
                                self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
                            if value == "1":
                                config["dns"]["optimistic"] = True
                                conflict = subprocess.run([CORE, "check", "-c", "stdin"], input=json.dumps(config), capture_output=True, text=True, encoding="utf-8")
                                self.assertNotEqual(conflict.returncode, 0)
                                self.assertIn("optimistic` is conflict with `disable_expire", conflict.stdout + conflict.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
