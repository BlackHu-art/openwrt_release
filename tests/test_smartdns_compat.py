#!/usr/bin/env python3
"""Exercise guarded SmartDNS downloads and the actual source-update stage."""
import hashlib
import importlib.util
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from shell_test_helpers import bash_executable, bash_path


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "maintenance/plugins/smartdns/package"
COMPAT = ROOT / "wrt_core/smartdns_compat.py"
ORIGINAL_SHA256 = "e0e6589e5031683536bda4665dcbf928cde0fe45c228f74b7ebaab02be342907"
SOURCE_COMMIT = b"3261c18b1b93d841e86d9e727557109ae71d71cd"
ARCHIVE_HASH = b"4401734712dd034eb1088ce440d1bc64d053dfcd6f63f66c08cd48ab68593042"


def snapshot(directory):
    return {p.relative_to(directory).as_posix(): p.read_bytes()
            for p in directory.rglob("*") if p.is_file()}


def expected_recipe(original):
    return original.replace(
        b"\tVERSION:=$(SMARTDNS_WEBUI_SOURCE_VERSION)\n",
        b"\tSOURCE_VERSION:=$(SMARTDNS_WEBUI_SOURCE_VERSION)\n",
    ).replace(
        b"$(eval $(call Download,smartdns-webui))\n",
        b"ifneq ($(filter y m,$(CONFIG_PACKAGE_smartdns-ui)),)\n"
        b"$(eval $(call Download,smartdns-webui))\nendif\n",
    )


class SmartdnsCompatibility(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="smartdns-compat-")
        self.addCleanup(temporary.cleanup)
        self.temporary = Path(temporary.name)
        self.build = self.temporary / "build"
        self.package = self.build / "feeds/packages/net/smartdns"
        self.package.mkdir(parents=True)
        self.recipe = self.package / "Makefile"
        self.original = (RAW / "Makefile").read_bytes()
        self.assertEqual(hashlib.sha256(self.original).hexdigest(), ORIGINAL_SHA256)
        self.recipe.write_bytes(self.original)

    def adapter(self):
        self.assertTrue(COMPAT.is_file(), "SmartDNS compatibility helper is not implemented")
        spec = importlib.util.spec_from_file_location("smartdns_compat_test", COMPAT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def assert_rejected_without_writes(self):
        before = snapshot(self.package)
        with self.assertRaises(ValueError):
            self.adapter().prepare(self.package)
        self.assertEqual(snapshot(self.package), before)

    def test_changes_only_download_version_field_and_selected_ui_registration(self):
        before = snapshot(RAW)
        self.adapter().prepare(self.package)
        self.assertEqual(self.recipe.read_bytes(), expected_recipe(self.original))
        self.assertEqual(snapshot(RAW), before)
        self.assertIn(SOURCE_COMMIT, self.recipe.read_bytes())
        self.assertIn(ARCHIVE_HASH, self.recipe.read_bytes())

    def test_unrelated_clone_metadata_and_patches_are_preserved(self):
        (self.package / ".git").mkdir()
        (self.package / ".git/config").write_bytes(b"clone metadata\n")
        (self.package / "patches").mkdir()
        (self.package / "patches/existing.patch").write_bytes(b"existing patch\n")
        (self.package / "additional-file").write_bytes(b"additional payload\n")
        expected = snapshot(self.package)
        expected["Makefile"] = expected_recipe(self.original)
        self.adapter().prepare(self.package)
        self.assertEqual(snapshot(self.package), expected)

    def test_prepared_recipe_is_revalidated_without_rewriting_and_mode_is_preserved(self):
        self.recipe.chmod(0o640 if os.name != "nt" else 0o666)
        mode = stat.S_IMODE(self.recipe.stat().st_mode)
        adapter = self.adapter()
        adapter.prepare(self.package)
        self.assertEqual(stat.S_IMODE(self.recipe.stat().st_mode), mode)
        before = snapshot(self.package)
        stamp = self.recipe.stat().st_mtime_ns
        adapter.prepare(self.package)
        self.assertEqual(snapshot(self.package), before)
        self.assertEqual(self.recipe.stat().st_mtime_ns, stamp)

    def test_partial_adaptations_and_selection_guard_drift_are_rejected(self):
        prepared = expected_recipe(self.original)
        candidates = (
            self.original.replace(b"\tVERSION:=", b"\tSOURCE_VERSION:="),
            prepared.replace(b"\tSOURCE_VERSION:=", b"\tVERSION:="),
            prepared.replace(b"filter y m,", b"filter y,"),
            prepared.replace(b"filter y m,", b"filter m,"),
            prepared.replace(b"filter y m,", b"filter y m n,"),
            prepared + b"\n$(eval $(call Download,smartdns-webui))\n",
        )
        for candidate in candidates:
            with self.subTest(recipe=candidate[-180:]):
                self.recipe.write_bytes(candidate)
                self.assert_rejected_without_writes()

    def test_source_hash_build_and_other_recipe_drift_are_rejected_in_both_states(self):
        mutations = (
            (b"pymumu/smartdns-webui.git", b"other/smartdns-webui.git"),
            (SOURCE_COMMIT, b"0" * 40),
            (ARCHIVE_HASH, b"skip"),
            (ARCHIVE_HASH, b"88adb092ed7b0dc22b3964249f4969870d3b462c4d924aceb18784c0f664f16e"),
            (b"\tSUBDIR:=smartdns-webui", b"\tSUBDIR:=other"),
            (b"CC=$(TARGET_CC)", b'CC="$(TARGET_CC_NOCACHE)"'),
            (b"PKG_RELEASE:=1", b"PKG_RELEASE:=2"),
            (b"\tnpm install", b"\tnpm ci"),
        )
        for prepared in (False, True):
            baseline = expected_recipe(self.original) if prepared else self.original
            for old, new in mutations:
                with self.subTest(prepared=prepared, field=old):
                    self.assertIn(old, baseline)
                    self.recipe.write_bytes(baseline.replace(old, new))
                    self.assert_rejected_without_writes()
            self.recipe.write_bytes(baseline + b"\n# unexpected change\n")
            self.assert_rejected_without_writes()

    def test_missing_recipe_or_non_directory_is_rejected(self):
        self.recipe.unlink()
        self.assert_rejected_without_writes()
        with self.assertRaises(ValueError):
            self.adapter().prepare(self.temporary / "missing")
        ordinary_file = self.temporary / "ordinary-file"
        ordinary_file.write_bytes(b"unchanged")
        with self.assertRaises(ValueError):
            self.adapter().prepare(ordinary_file)
        self.assertEqual(ordinary_file.read_bytes(), b"unchanged")

    def test_makefile_symlink_is_rejected_without_writing_its_target(self):
        outside = self.temporary / "outside.mk"
        outside.write_bytes(self.original)
        adapter = self.adapter()
        if os.name == "nt":
            # This Windows runner lacks SeCreateSymbolicLinkPrivilege. Exercise
            # the OS metadata boundary here; Linux creates the actual symlink.
            is_symlink = Path.is_symlink
            with mock.patch.object(Path, "is_symlink", lambda p: p == self.recipe or is_symlink(p)):
                with self.assertRaises(ValueError):
                    adapter.prepare(self.package)
            self.assertEqual(self.recipe.read_bytes(), self.original)
        else:
            self.recipe.unlink()
            self.recipe.symlink_to(outside)
            with self.assertRaises(ValueError):
                adapter.prepare(self.package)
            self.assertTrue(self.recipe.is_symlink())
        self.assertEqual(outside.read_bytes(), self.original)

    def test_package_symlink_is_rejected_without_writing_real_package(self):
        alias = self.temporary / "package-alias"
        adapter = self.adapter()
        if os.name == "nt":
            alias.mkdir()
            (alias / "Makefile").write_bytes(self.original)
            is_symlink = Path.is_symlink
            with mock.patch.object(Path, "is_symlink", lambda p: p == alias or is_symlink(p)):
                with self.assertRaises(ValueError):
                    adapter.prepare(alias)
            self.assertEqual((alias / "Makefile").read_bytes(), self.original)
        else:
            alias.symlink_to(self.package, target_is_directory=True)
            with self.assertRaises(ValueError):
                adapter.prepare(alias)
        self.assertEqual(self.recipe.read_bytes(), self.original)

    def test_maintenance_original_cannot_be_a_destination(self):
        before = snapshot(RAW)
        with self.assertRaises(ValueError):
            self.adapter().prepare(RAW)
        self.assertEqual(snapshot(RAW), before)

    def test_reviewed_source_drift_is_rejected_before_writing_build_recipe(self):
        adapter = self.adapter()
        source = self.temporary / "reviewed-source"
        source.mkdir()
        (source / "Makefile").write_bytes(self.original + b"\n# drift\n")
        with mock.patch.object(adapter, "RAW", source):
            with self.assertRaises(ValueError):
                adapter.prepare(self.package)
        self.assertEqual(self.recipe.read_bytes(), self.original)

    def test_failed_atomic_replace_preserves_recipe_and_cleans_temporary_file(self):
        adapter = self.adapter()
        before = snapshot(self.package)
        with mock.patch.object(adapter.os, "replace", side_effect=OSError("injected replace failure")):
            with self.assertRaises(OSError):
                adapter.prepare(self.package)
        self.assertEqual(snapshot(self.package), before)
        self.assertEqual(sorted(p.name for p in self.package.iterdir()), ["Makefile"])

    def test_cli_applies_and_returns_failure_on_later_drift(self):
        result = subprocess.run([sys.executable, str(COMPAT), str(self.package)],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.recipe.read_bytes(), expected_recipe(self.original))
        self.recipe.write_bytes(self.recipe.read_bytes() + b"\n# drift\n")
        before = snapshot(self.package)
        result = subprocess.run([sys.executable, str(COMPAT), str(self.package)],
                                capture_output=True, text=True, timeout=20)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SmartDNS", result.stderr)
        self.assertEqual(snapshot(self.package), before)

    def run_update(self, *, stage=False, drift=False, failure=""):
        fixture = self.temporary / "clone-fixture"
        fixture.mkdir()
        (fixture / "Makefile").write_bytes(self.original + (b"\n# upstream drift\n" if drift else b""))
        # Execute the real SmartDNS function and stage. Replace only unrelated
        # hooks and remote clone I/O, including the unavailable LuCI repository.
        script = r'''set -uo pipefail
source "$BASE_PATH/update.sh"
while read -r _ _ name; do
    case "$name" in update_smartdns|stage_pre_install_source_fixes) ;;
        *) eval "$name() { :; }" ;;
    esac
done < <(declare -F)
python3() {
    case "$1" in */simple_obfs_compat.py) return 0 ;; esac
    "$TEST_PYTHON" "$@"
}
fail_io() {
    printf '%s\n' "$TEST_FAILURE" > "$BUILD_DIR/io-failure-reached"
    return 55
}
rm() {
    if [ "$#" -eq 2 ] && [ "$1" = -rf ]; then
        case "$TEST_FAILURE:$2" in
            "smartdns-rm:$BUILD_DIR/feeds/packages/net/smartdns"|\
            "luci-rm:$BUILD_DIR/feeds/luci/applications/luci-app-smartdns")
                fail_io; return $? ;;
        esac
    fi
    command rm "$@"
}
install() {
    if [ "$TEST_FAILURE" = patch-install ]; then fail_io; return $?; fi
    command install "$@"
}
sed() {
    if [ "$TEST_FAILURE" = cc-sed ]; then fail_io; return $?; fi
    command sed "$@"
}
git_retry() {
    [ "$#" -eq 4 ] && [ "$1" = clone ] && [ "$2" = --depth=1 ] || return 91
    case "$3" in
        https://github.com/ZqinKing/openwrt-smartdns.git)
            [ "$4" = "$BUILD_DIR/feeds/packages/net/smartdns" ] || return 92
            mkdir -p "$4/.git"
            cp "$TEST_FIXTURE/Makefile" "$4/Makefile"
            printf 'clone metadata\n' > "$4/.git/config"
            ;;
        https://github.com/pymumu/luci-app-smartdns.git)
            [ "$4" = "$BUILD_DIR/feeds/luci/applications/luci-app-smartdns" ] || return 93
            mkdir -p "$4"
            touch "$BUILD_DIR/luci-clone-reached"
            ;;
        *) return 94 ;;
    esac
}
get_custom_feed_worktree_dir() { printf '%s/custom_feed\n' "$BUILD_DIR"; }
update_mwan3_fw4() { touch "$BUILD_DIR/later-hook-reached"; }
if "$TEST_ENTRY"; then status=0; else status=$?; fi
exit "$status"
'''
        environment = dict(os.environ, BASE_PATH=bash_path(ROOT / "wrt_core"),
                           BUILD_DIR=bash_path(self.build), TEST_FIXTURE=bash_path(fixture),
                           TEST_FAILURE=failure,
                           TEST_PYTHON=Path(sys.executable).as_posix(),
                           TEST_ENTRY="stage_pre_install_source_fixes" if stage else "update_smartdns",
                           PYTHONDONTWRITEBYTECODE="1")
        return subprocess.run([bash_executable(), "--noprofile", "--norc", "-c", script],
                              env=environment, capture_output=True, text=True, timeout=30)

    def test_real_update_applies_adapter_before_existing_patch_and_cc_changes(self):
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        expected = expected_recipe(self.original).replace(b"CC=$(TARGET_CC)", b'CC="$(TARGET_CC_NOCACHE)"')
        self.assertEqual(self.recipe.read_bytes(), expected)
        self.assertEqual((self.package / "patches/100-smartdns-optimize.patch").read_bytes(),
                         (ROOT / "wrt_core/patches/100-smartdns-optimize.patch").read_bytes())
        self.assertTrue((self.build / "luci-clone-reached").is_file())

    def test_real_update_stops_before_patch_cc_and_luci_on_unreviewed_recipe(self):
        result = self.run_update(drift=True)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.recipe.read_bytes(), self.original + b"\n# upstream drift\n")
        self.assertFalse((self.package / "patches/100-smartdns-optimize.patch").exists())
        self.assertFalse((self.build / "luci-clone-reached").exists())

    def test_real_stage_propagates_failure_even_when_called_in_an_if_condition(self):
        result = self.run_update(stage=True, drift=True)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.build / "later-hook-reached").exists())
        self.assertFalse((self.build / "luci-clone-reached").exists())
        self.assertEqual(self.recipe.read_bytes(), self.original + b"\n# upstream drift\n")

    def test_real_stage_runs_later_hooks_after_successful_smartdns_preparation(self):
        result = self.run_update(stage=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.build / "later-hook-reached").is_file())
        self.assertTrue((self.build / "luci-clone-reached").is_file())
        self.assertEqual(self.recipe.read_bytes(), expected_recipe(self.original).replace(
            b"CC=$(TARGET_CC)", b'CC="$(TARGET_CC_NOCACHE)"'))

    def assert_stage_io_failure_stops(self, failure, *, adapted, patch, cc_changed):
        luci = self.build / "feeds/luci/applications/luci-app-smartdns"
        luci.mkdir(parents=True)
        (luci / "existing-file").write_bytes(b"existing LuCI package\n")
        result = self.run_update(stage=True, failure=failure)
        self.assertEqual((self.build / "io-failure-reached").read_text().strip(), failure)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.build / "later-hook-reached").exists())
        self.assertFalse((self.build / "luci-clone-reached").exists())
        self.assertEqual((luci / "existing-file").read_bytes(), b"existing LuCI package\n")
        expected = expected_recipe(self.original) if adapted else self.original
        if cc_changed:
            expected = expected.replace(b"CC=$(TARGET_CC)", b'CC="$(TARGET_CC_NOCACHE)"')
        self.assertEqual(self.recipe.read_bytes(), expected)
        installed = self.package / "patches/100-smartdns-optimize.patch"
        if patch:
            self.assertEqual(installed.read_bytes(),
                             (ROOT / "wrt_core/patches/100-smartdns-optimize.patch").read_bytes())
        else:
            self.assertFalse(installed.exists())

    def test_real_stage_stops_when_removing_previous_smartdns_package_fails(self):
        self.assert_stage_io_failure_stops("smartdns-rm", adapted=False, patch=False, cc_changed=False)
        self.assertFalse((self.package / ".git/config").exists())

    def test_real_stage_stops_when_installing_smartdns_patch_fails(self):
        self.assert_stage_io_failure_stops("patch-install", adapted=True, patch=False, cc_changed=False)

    def test_real_stage_stops_when_updating_smartdns_compiler_fails(self):
        self.assert_stage_io_failure_stops("cc-sed", adapted=True, patch=True, cc_changed=False)

    def test_real_stage_stops_when_removing_previous_luci_package_fails(self):
        self.assert_stage_io_failure_stops("luci-rm", adapted=True, patch=True, cc_changed=True)


if __name__ == "__main__":
    unittest.main()
