#!/usr/bin/env python3
"""Exercise the real Xray recipe gate without downloads or firmware builds."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "wrt_core/modules/xray_core_compat.sh"
FIXTURE = ROOT / "maintenance/plugins/ssrplus/upstream-v198.2/xray-core"
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
        shutil.copytree(FIXTURE, self.package)
        self.recipe = self.package / "Makefile"
        self.generators = []
        for plugin in ("passwall2",):
            generator = self.feed / f"luci-app-{plugin}/luasrc/{plugin}/util_xray.lua"
            generator.parent.mkdir(parents=True)
            generator.write_text('local xray_min_version = "26.7.11"\n', encoding="utf-8")
            self.generators.append(generator)
        self.go_recipe = self.build / "feeds/packages/lang/golang/golang/Makefile"
        self.go_recipe.parent.mkdir(parents=True)
        self.go_recipe.write_text("GO_VERSION_MAJOR_MINOR:=1.27\nGO_VERSION_PATCH:=3\n", encoding="utf-8")
        self.env = os.environ.copy()
        self.env.update(BASE_PATH=(ROOT / "wrt_core").as_posix(),
                        BUILD_DIR=self.build.as_posix(),
                        XRAY_PACKAGE=self.package.as_posix(), TEST_PYTHON=Path(sys.executable).as_posix())

    def apply(self):
        command = ('python3() { "$TEST_PYTHON" "$@"; }; if [ -f "$BASE_PATH/modules/xray_core_compat.sh" ]; then '
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

    def test_reviewed_fw_recipe_and_all_private_protocol_patches_are_accepted_unchanged(self):
        before = self.snapshot()
        result = self.apply()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(list((self.package / "patches").glob("*.patch"))), 10)
        self.assertEqual(self.snapshot(), before)

    def test_every_private_protocol_patch_is_required_and_verified(self):
        for patch in sorted((self.package / "patches").glob("*.patch")):
            original = patch.read_bytes()
            for mutation in ("missing", "modified"):
                with self.subTest(patch=patch.name, mutation=mutation):
                    if mutation == "missing":
                        patch.unlink()
                    else:
                        patch.write_bytes(original + b"\n# unreviewed patch\n")
                    self.assert_rejected_without_changes(patch.name)
                    patch.write_bytes(original)

    def test_extra_patch_is_rejected_before_build(self):
        (self.package / "patches/999-unreviewed.patch").write_bytes(b"unreviewed")
        self.assert_rejected_without_changes("999-unreviewed.patch")

    def test_official_recipe_without_fw_patches_is_rejected(self):
        shutil.rmtree(self.package / "patches")
        official = ROOT / "tests/fixtures/proxy-cores/small-package-3d560925/xray-core/Makefile"
        self.recipe.write_bytes(official.read_bytes())
        self.assert_rejected_without_changes("xray-core")

    def test_passwall2_only_tree_needs_no_passwall1_source(self):
        self.assertFalse((self.feed / "luci-app-passwall").exists())
        result = self.apply()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

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

    def test_changed_recipe_version_with_stale_hash_is_rejected(self):
        self.recipe.write_bytes(self.recipe.read_bytes().replace(b"26.10.21", b"26.10.22"))
        self.assert_rejected_without_changes("Makefile")

    def test_passwall2_minimum_is_rechecked_after_successful_validation(self):
        result = self.apply()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for generator in self.generators:
            with self.subTest(generator=generator.name, plugin=generator.parent.name):
                generator.write_text('local xray_min_version = "26.10.22"\n', encoding="utf-8")
                self.assert_rejected_without_changes("26.10.22")
                generator.write_text('local xray_min_version = "26.7.11"\n', encoding="utf-8")

    def test_newer_generator_requirement_rejects_fw_recipe_without_write(self):
        self.generators[0].write_text('local xray_min_version = "26.10.22"\n', encoding="utf-8")
        self.assert_rejected_without_changes("26.10.22")

    def test_missing_or_ambiguous_generator_requirement_is_rejected(self):
        self.generators[0].unlink()
        self.assert_rejected_without_changes("Passwall2")
        self.generators[0].write_text('local xray_min_version = "26.7.11"\n' * 2, encoding="utf-8")
        self.assert_rejected_without_changes("Passwall2")

    def test_changed_generator_declaration_cannot_hide_behind_an_old_valid_one(self):
        self.generators[0].write_text(
            'local xray_min_version = "26.7.11"\nlocal xray_min_version = next_version\n',
            encoding="utf-8")
        self.assert_rejected_without_changes("Passwall2")

    def test_old_or_missing_go_toolchain_is_rejected_without_write(self):
        self.go_recipe.write_text("GO_VERSION_MAJOR_MINOR:=1.26\n", encoding="utf-8")
        self.assert_rejected_without_changes("Go")
        self.go_recipe.unlink()
        self.assert_rejected_without_changes("Go")

    def test_changed_go_declaration_cannot_hide_behind_a_valid_one(self):
        self.go_recipe.write_text("GO_VERSION_MAJOR_MINOR:=1.27\nGO_VERSION_MAJOR_MINOR:=$(NEXT_GO)\n", encoding="utf-8")
        self.assert_rejected_without_changes("Go")

    def test_go_1272_is_rejected_for_security_floor(self):
        self.go_recipe.write_text("GO_VERSION_MAJOR_MINOR:=1.27\nGO_VERSION_PATCH:=2\n", encoding="utf-8")
        self.assert_rejected_without_changes("Go")

    def test_go_patch_must_be_unique_literal_and_is_rechecked_on_cached_recipe(self):
        result = self.apply()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for patch in ("", "GO_VERSION_PATCH:=3\nGO_VERSION_PATCH:=4\n", "GO_VERSION_PATCH:=$(NEXT_PATCH)\n"):
            with self.subTest(patch=patch):
                self.go_recipe.write_text("GO_VERSION_MAJOR_MINOR:=1.27\n" + patch, encoding="utf-8")
                self.assert_rejected_without_changes("Go")

    def test_compatible_lower_consumer_minimum_and_newer_go_are_allowed(self):
        self.generators[0].write_text('local xray_min_version = "26.4.17"\n', encoding="utf-8")
        self.go_recipe.write_text("GO_VERSION_MAJOR_MINOR:=1.28\nGO_VERSION_PATCH:=0\n", encoding="utf-8")
        result = self.apply()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(b"PKG_VERSION:=26.10.21\n", self.recipe.read_bytes())

    def test_package_nested_in_git_repository_validates_the_actual_recipe(self):
        result = subprocess.run(["git", "init", "-q", str(self.build)], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.apply()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(b"PKG_VERSION:=26.10.21\n", self.recipe.read_bytes())

    def test_missing_source_lock_is_rejected_without_publishing_any_change(self):
        base = self.build / "compat"
        (base / "modules").mkdir(parents=True)
        shutil.copyfile(MODULE, base / "modules/xray_core_compat.sh")
        self.env["BASE_PATH"] = base.as_posix()
        self.assert_rejected_without_changes("Xray")


class GoToolchainSourceUpdate(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="go-toolchain-update-")
        self.addCleanup(self.temp.cleanup)
        self.build = Path(self.temp.name)
        self.target = self.build / "feeds/packages/lang/golang"
        self.fixture = self.build / "downloaded-Makefile"
        self.fixture.write_text("GO_VERSION_MAJOR_MINOR:=1.27\nGO_VERSION_PATCH:=3\n", encoding="utf-8")
        self.env = dict(os.environ, BASE_PATH=(ROOT / "wrt_core").as_posix(),
                        BUILD_DIR=self.build.as_posix(), GO_FIXTURE=self.fixture.as_posix(),
                        CLONE_FAIL="0")

    def apply(self):
        command = r'''
cd "$BUILD_DIR" || exit
. "$BASE_PATH/update.sh" || exit
git_retry() {
    [[ "$CLONE_FAIL" == 0 ]] || return 1
    [[ "$1" == clone && "$2" == --depth && "$3" == 1 && "$4" == -b && "$5" == 27.x && "$6" == https://github.com/sbwml/packages_lang_golang ]] || return 2
    mkdir -p "$7/golang" || return
    cp "$GO_FIXTURE" "$7/golang/Makefile"
}
mv() {
    if [[ "${PUBLISH_FAIL:-0}" == 1 && "$2" == */source ]]; then return 1; fi
    if [[ "${ROLLBACK_FAIL:-0}" == 1 && "$2" == */previous ]]; then return 1; fi
    command mv "$@"
}
update_golang
'''
        return subprocess.run([BASH, "--noprofile", "--norc", "-c", command], env=self.env,
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)

    def seed_old_source(self):
        self.target.mkdir(parents=True)
        (self.target / "previous").write_bytes(b"old source must survive failed replacement")

    def test_missing_source_is_installed_from_required_branch(self):
        result = self.apply()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.target / "golang/Makefile").is_file())
        self.assertEqual((self.target / "golang/Makefile").read_bytes(), self.fixture.read_bytes())

    def test_existing_source_is_refreshed_only_after_verified_clone(self):
        self.seed_old_source()
        result = self.apply()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.target / "golang/Makefile").read_bytes(), self.fixture.read_bytes())
        self.assertFalse((self.target / "previous").exists())

    def test_failed_clone_preserves_previous_source(self):
        self.seed_old_source()
        self.env["CLONE_FAIL"] = "1"
        result = self.apply()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.target / "previous").read_bytes(), b"old source must survive failed replacement")

    def test_publication_failure_restores_previous_source(self):
        self.seed_old_source()
        self.env["PUBLISH_FAIL"] = "1"
        result = self.apply()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.target / "previous").read_bytes(), b"old source must survive failed replacement")

    def test_failed_rollback_keeps_previous_source_recoverable(self):
        self.seed_old_source()
        self.env.update(PUBLISH_FAIL="1", ROLLBACK_FAIL="1")
        result = self.apply()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        backups = list(self.target.parent.glob(".golang-update.*/previous/previous"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), b"old source must survive failed replacement")

    def test_old_or_ambiguous_toolchain_cannot_replace_previous_source(self):
        self.seed_old_source()
        for recipe in ("GO_VERSION_MAJOR_MINOR:=1.26\nGO_VERSION_PATCH:=10\n",
                       "GO_VERSION_MAJOR_MINOR:=1.27\nGO_VERSION_PATCH:=2\n",
                       "GO_VERSION_MAJOR_MINOR:=1.27\nGO_VERSION_PATCH:=3\nGO_VERSION_PATCH:=4\n"):
            with self.subTest(recipe=recipe):
                self.fixture.write_text(recipe, encoding="utf-8")
                result = self.apply()
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual((self.target / "previous").read_bytes(), b"old source must survive failed replacement")


if __name__ == "__main__":
    unittest.main()
