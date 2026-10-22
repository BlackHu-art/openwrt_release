#!/usr/bin/env python3
"""Exercise the real Xray recipe gate without downloads or firmware builds."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "wrt_core/modules/xray_core_compat.sh"
FIXTURE = ROOT / "tests/fixtures/proxy-cores/small-package-3d560925/xray-core/Makefile"
BASH = os.environ.get("BASH") or shutil.which("bash")
if os.name == "nt" and not BASH:
    BASH = "C:/Program Files/Git/bin/bash.exe"


class XrayRecipeCompatibility(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="xray-core-compat-")
        self.addCleanup(self.temp.cleanup)
        self.build = Path(self.temp.name)
        self.feed = self.build / "feeds/custom_feed"
        self.package = self.feed / "xray-core"
        self.package.mkdir(parents=True)
        self.recipe = self.package / "Makefile"
        shutil.copyfile(FIXTURE, self.recipe)
        self.generators = []
        for plugin in ("passwall", "passwall2"):
            generator = self.feed / f"luci-app-{plugin}/luasrc/{plugin}/util_xray.lua"
            generator.parent.mkdir(parents=True)
            generator.write_text('local xray_min_version = "26.7.11"\n', encoding="utf-8")
            self.generators.append(generator)
        self.go_recipe = self.build / "feeds/packages/lang/golang/golang/Makefile"
        self.go_recipe.parent.mkdir(parents=True)
        self.go_recipe.write_text("GO_VERSION_MAJOR_MINOR:=1.26\nGO_VERSION_PATCH:=10\n", encoding="utf-8")
        self.env = os.environ.copy()
        self.env.update(BASE_PATH=(ROOT / "wrt_core").as_posix(),
                        BUILD_DIR=self.build.as_posix(),
                        XRAY_PACKAGE=self.package.as_posix())

    def apply(self):
        # The no-op when absent reproduces the existing, unpatched source flow.
        command = ('if [ -f "$BASE_PATH/modules/xray_core_compat.sh" ]; then '
                   '. "$BASE_PATH/modules/xray_core_compat.sh" || exit; '
                   'fix_xray_core_compat "$XRAY_PACKAGE"; fi')
        return subprocess.run([BASH, "--noprofile", "--norc", "-c", command],
                              env=self.env, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=30)

    def snapshot(self):
        return {p.relative_to(self.build).as_posix(): p.read_bytes()
                for p in self.build.rglob("*") if p.is_file()}

    def assert_rejected_without_changes(self, expected):
        before = self.snapshot()
        result = self.apply()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(expected, result.stderr)
        self.assertEqual(self.snapshot(), before)

    def test_reviewed_recipe_gets_required_version_and_verified_archive_hash(self):
        result = self.apply()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        recipe = self.recipe.read_text(encoding="utf-8")
        self.assertIn("PKG_VERSION:=26.7.11\n", recipe)
        self.assertIn("PKG_HASH:=7c191254c0d8cc8be7673904739fc7329b601947da5377ef85900a0cd0a85e23\n", recipe)
        self.assertIn("PKG_SOURCE_URL:=https://codeload.github.com/XTLS/Xray-core/tar.gz/v$(PKG_VERSION)?\n", recipe)
        expected = FIXTURE.read_bytes().replace(b"PKG_VERSION:=26.3.27", b"PKG_VERSION:=26.7.11").replace(
            b"992a4997e6bb846d11469435d687f99ef812fcde1e0a009bb8e95189ea20331d",
            b"7c191254c0d8cc8be7673904739fc7329b601947da5377ef85900a0cd0a85e23")
        self.assertEqual(self.recipe.read_bytes(), expected)

    def test_repeat_is_idempotent_and_does_not_rewrite_recipe(self):
        first = self.apply()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        before = self.snapshot()
        stamp = self.recipe.stat().st_mtime_ns
        second = self.apply()
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.recipe.stat().st_mtime_ns, stamp)

    def test_recipe_drift_outside_patch_hunks_fails_before_any_write(self):
        self.recipe.write_bytes(self.recipe.read_bytes() + b"\n# unreviewed dependency change\n")
        self.assert_rejected_without_changes("Makefile")

    def test_partial_upgrade_with_stale_hash_is_rejected(self):
        self.recipe.write_bytes(self.recipe.read_bytes().replace(b"26.3.27", b"26.7.11"))
        self.assert_rejected_without_changes("Makefile")

    def test_both_consumers_are_checked_again_when_recipe_already_patched(self):
        result = self.apply()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for generator in self.generators:
            with self.subTest(generator=generator.name, plugin=generator.parent.name):
                generator.write_text('local xray_min_version = "26.7.12"\n', encoding="utf-8")
                self.assert_rejected_without_changes("26.7.12")
                generator.write_text('local xray_min_version = "26.7.11"\n', encoding="utf-8")

    def test_newer_generator_requirement_rejects_unpatched_recipe_without_write(self):
        self.generators[0].write_text('local xray_min_version = "26.10.1"\n', encoding="utf-8")
        self.assert_rejected_without_changes("26.10.1")

    def test_missing_or_ambiguous_generator_requirement_is_rejected(self):
        self.generators[1].unlink()
        self.assert_rejected_without_changes("Passwall2")
        self.generators[1].write_text('local xray_min_version = "26.7.11"\n' * 2, encoding="utf-8")
        self.assert_rejected_without_changes("Passwall2")

    def test_changed_generator_declaration_cannot_hide_behind_an_old_valid_one(self):
        self.generators[1].write_text(
            'local xray_min_version = "26.7.11"\nlocal xray_min_version = next_version\n',
            encoding="utf-8")
        self.assert_rejected_without_changes("Passwall2")

    def test_old_or_missing_go_toolchain_is_rejected_without_write(self):
        self.go_recipe.write_text("GO_VERSION_MAJOR_MINOR:=1.25\n", encoding="utf-8")
        self.assert_rejected_without_changes("Go")
        self.go_recipe.unlink()
        self.assert_rejected_without_changes("Go")

    def test_changed_go_declaration_cannot_hide_behind_a_valid_one(self):
        self.go_recipe.write_text("GO_VERSION_MAJOR_MINOR:=1.26\nGO_VERSION_MAJOR_MINOR:=$(NEXT_GO)\n", encoding="utf-8")
        self.assert_rejected_without_changes("Go")

    def test_compatible_lower_consumer_minimum_and_newer_go_are_allowed(self):
        self.generators[0].write_text('local xray_min_version = "26.4.17"\n', encoding="utf-8")
        self.go_recipe.write_text("GO_VERSION_MAJOR_MINOR:=1.27\n", encoding="utf-8")
        result = self.apply()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(b"PKG_VERSION:=26.7.11\n", self.recipe.read_bytes())

    def test_package_nested_in_git_repository_updates_the_actual_recipe(self):
        result = subprocess.run(["git", "init", "-q", str(self.build)], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.apply()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(b"PKG_VERSION:=26.7.11\n", self.recipe.read_bytes())

    def test_modified_patch_result_is_rejected_without_publishing_any_change(self):
        base = self.build / "compat"
        (base / "modules").mkdir(parents=True)
        (base / "patches").mkdir()
        shutil.copyfile(MODULE, base / "modules/xray_core_compat.sh")
        patch = (ROOT / "wrt_core/patches/xray-core-26.7.11.patch").read_bytes()
        (base / "patches/xray-core-26.7.11.patch").write_bytes(
            patch.replace(b"+PKG_VERSION:=26.7.11", b"+PKG_VERSION:=26.7.12"))
        self.env["BASE_PATH"] = base.as_posix()
        self.assert_rejected_without_changes("Xray")

    def test_missing_patch_is_rejected_without_publishing_any_change(self):
        base = self.build / "compat"
        (base / "modules").mkdir(parents=True)
        shutil.copyfile(MODULE, base / "modules/xray_core_compat.sh")
        self.env["BASE_PATH"] = base.as_posix()
        self.assert_rejected_without_changes("Xray")

    def test_scratch_nested_inside_another_git_root_still_applies_patch(self):
        subprocess.run(["git", "init", "-q", str(self.build)], check=True)
        scratch = self.build / "scratch"
        scratch.mkdir()
        self.env["TMPDIR"] = scratch.as_posix()
        result = self.apply()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(b"PKG_VERSION:=26.7.11\n", self.recipe.read_bytes())
        self.assertEqual(list(scratch.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
