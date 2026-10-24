#!/usr/bin/env python3
"""Exercise real module loading, pre-install core checks and failure propagation."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

import shell_test_helpers as shell

ROOT = Path(__file__).resolve().parents[1]


class ProxyCompatibilityPipeline(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="proxy-pipeline-")
        self.addCleanup(self.temp.cleanup)
        self.build = Path(self.temp.name)
        self.feed = self.build / "feeds/custom_feed"
        # The independent upstream capture must pass the actual managed gate.
        shutil.copytree(ROOT / "maintenance/plugins/ssrplus/upstream-v198.2/xray-core",
                        self.feed / "xray-core")
        self.go_recipe = self.build / "feeds/packages/lang/golang/golang/Makefile"
        self.go_recipe.parent.mkdir(parents=True)
        self.go_recipe.write_text("GO_VERSION_MAJOR_MINOR:=1.25\n", encoding="utf-8")
        self.refreshed_go = self.build / "refreshed-go"
        self.refreshed_go.write_text("GO_VERSION_MAJOR_MINOR:=1.27\nGO_VERSION_PATCH:=3\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(self.build)], check=True)

    def prepare(self):
        source = (ROOT / "wrt_core/update.sh").read_text(encoding="utf-8")
        stage = re.search(r"(?ms)^stage_pre_install_source_fixes\(\) \{\n(.*?)^\}", source).group(1)
        commands = re.findall(r"^    ([a-z_][a-z_0-9]*)\b", stage, re.M)
        preserved = {"fix_xray_core_compat", "update_golang", "python3"}
        # Other plugins have dedicated source-preparation suites. Only their
        # preparation boundaries are replaced; module loading and this stage run.
        stubs = "\n".join(name + "() { :; }" for name in commands if name not in preserved)
        script = r'''source "$BASE_PATH/update.sh" || exit
for helper in fix_xray_core_compat fix_ssrplus_compat install_managed_package; do
    declare -F "$helper" >/dev/null || exit 91
done
python3() {
    case "$1" in */simple_obfs_compat.py) return 0;; esac
    "$TEST_PYTHON" "$@"
}
''' + stubs + r'''
update_golang() {
    cp "$TEST_GO_RECIPE" "$BUILD_DIR/feeds/packages/lang/golang/golang/Makefile"
}
change_dnsmasq2full() { touch "$BUILD_DIR/passed-core-gate"; }
stage_pre_install_source_fixes
'''
        env = dict(os.environ, BASE_PATH=shell.bash_path(ROOT / "wrt_core"),
                   BUILD_DIR=shell.bash_path(self.build), TEST_PYTHON=Path(sys.executable).as_posix(),
                   TEST_GO_RECIPE=shell.bash_path(self.refreshed_go))
        return subprocess.run([shell.bash_executable(), "--noprofile", "--norc", "-c", script],
                              env=env, capture_output=True, text=True, timeout=60)

    def test_pre_install_refreshes_go_then_validates_complete_core_without_config_changes(self):
        recipe = self.feed / "xray-core/Makefile"
        before = {p.relative_to(self.feed): p.read_bytes() for p in self.feed.rglob("*") if p.is_file()}
        result = self.prepare()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PKG_VERSION:=26.10.21\n", recipe.read_text(encoding="utf-8"))
        self.assertEqual(self.go_recipe.read_bytes(), self.refreshed_go.read_bytes())
        self.assertTrue((self.build / "passed-core-gate").exists())
        repeat = self.prepare()
        self.assertEqual(repeat.returncode, 0, repeat.stdout + repeat.stderr)
        self.assertEqual(before, {p.relative_to(self.feed): p.read_bytes()
                                 for p in self.feed.rglob("*") if p.is_file()})
        self.assertFalse((self.build / ".config").exists())

    def test_core_recipe_drift_stops_the_stage_before_downstream_changes(self):
        recipe = self.feed / "xray-core/Makefile"
        recipe.write_bytes(recipe.read_bytes() + b"\n# unreviewed drift\n")
        result = self.prepare()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Makefile", result.stdout + result.stderr)
        self.assertFalse((self.build / "passed-core-gate").exists())

    def test_missing_private_patch_stops_the_stage(self):
        patch = next((self.feed / "xray-core/patches").glob("*.patch"))
        patch.unlink()
        result = self.prepare()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(patch.name, result.stdout + result.stderr)
        self.assertFalse((self.build / "passed-core-gate").exists())

    def test_old_refreshed_go_stops_the_stage(self):
        self.refreshed_go.write_text("GO_VERSION_MAJOR_MINOR:=1.27\nGO_VERSION_PATCH:=2\n", encoding="utf-8")
        result = self.prepare()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Go", result.stdout + result.stderr)
        self.assertFalse((self.build / "passed-core-gate").exists())


if __name__ == "__main__":
    unittest.main()
