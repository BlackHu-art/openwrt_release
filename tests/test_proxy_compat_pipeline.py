#!/usr/bin/env python3
"""Exercise the real pre-install stage with local source trees and no network."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from lupa.lua51 import LuaError
import test_passwall2_tls as tls_tests


ROOT = Path(__file__).resolve().parents[1]


class ProxyCompatibilityPipeline(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="proxy-pipeline-")
        self.addCleanup(self.temp.cleanup)
        self.build = Path(self.temp.name)
        self.feed = self.build / "feeds/custom_feed"
        recipe = self.feed / "xray-core/Makefile"
        recipe.parent.mkdir(parents=True)
        shutil.copyfile(ROOT / "tests/fixtures/proxy-cores/small-package-3d560925/xray-core/Makefile", recipe)
        self.packages = {}
        for plugin in tls_tests.PLUGINS:
            original = ROOT / "maintenance/plugins" / plugin / ("luci-app-" + plugin)
            package = self.feed / ("luci-app-" + plugin)
            for relative in (f"luasrc/{plugin}/util_xray.lua", f"luasrc/{plugin}/util_sing-box.lua",
                             f"root/usr/share/{plugin}/app.sh"):
                target = package / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(original / relative, target)
            self.packages[plugin] = (package, original)
        self.go_recipe = self.build / "feeds/packages/lang/golang/golang/Makefile"
        self.go_recipe.parent.mkdir(parents=True)
        self.go_recipe.write_text("GO_VERSION_MAJOR_MINOR:=1.25\n", encoding="utf-8")
        # A real parent Git root exercises custom-feed package path handling.
        subprocess.run(["git", "init", "-q", str(self.build)], check=True)

    def prepare(self):
        source = (ROOT / "wrt_core/update.sh").read_text(encoding="utf-8")
        stage = re.search(r"(?ms)^stage_pre_install_source_fixes\(\) \{\n(.*?)^\}", source).group(1)
        # Only unrelated preparation/download boundaries are replaced. The
        # stage, new repair helpers, patch application and source checks run.
        commands = re.findall(r"^    ([a-z_][a-z_0-9]*)\b", stage, re.M)
        preserved = {"fix_xray_core_compat", "fix_passwall2_compat", "update_golang"}
        stubs = "\n".join(name + "() { :; }" for name in commands if name not in preserved)
        script = '''source "$BASE_PATH/update.sh"
''' + stubs + '''
update_golang() {
    printf 'GO_VERSION_MAJOR_MINOR:=1.27\nGO_VERSION_PATCH:=3\n' > "$BUILD_DIR/feeds/packages/lang/golang/golang/Makefile"
}
stage_pre_install_source_fixes
'''
        env = dict(os.environ, BASE_PATH=tls_tests.bash_path(ROOT / "wrt_core"),
                   BUILD_DIR=tls_tests.bash_path(self.build))
        return subprocess.run([tls_tests.bash_executable(), "--noprofile", "--norc", "-c", script],
                              env=env, capture_output=True, text=True, timeout=60)

    def test_pre_install_repairs_sources_after_go_refresh_without_config_changes(self):
        result = self.prepare()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        recipe = (self.feed / "xray-core/Makefile").read_text(encoding="utf-8")
        self.assertIn("PKG_VERSION:=26.10.21\n", recipe)
        for plugin, (package, original) in self.packages.items():
            with self.subTest(plugin=plugin):
                source = (package / f"luasrc/{plugin}/util_sing-box.lua").read_bytes()
                api = (original / f"luasrc/{plugin}/api.lua").read_text(encoding="utf-8")
                with self.assertRaisesRegex(LuaError, "certificate.*1[.]15"):
                    tls_tests.generate(source, api, "1.14.3", {"tls_pinSHA256": tls_tests.PIN_HEX})
        before = {p.relative_to(self.feed): p.read_bytes() for p in self.feed.rglob("*") if p.is_file()}
        repeat = self.prepare()
        self.assertEqual(repeat.returncode, 0, repeat.stdout + repeat.stderr)
        self.assertEqual(before, {p.relative_to(self.feed): p.read_bytes()
                                 for p in self.feed.rglob("*") if p.is_file()})
        self.assertFalse((self.build / ".config").exists())

    def test_unknown_plugin_source_stops_the_stage(self):
        package = self.packages["passwall2"][0]
        source = package / "luasrc/passwall2/util_sing-box.lua"
        source.write_text("unrecognized generator\n", encoding="utf-8")
        result = self.prepare()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("passwall", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
