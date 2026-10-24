#!/usr/bin/env python3
"""Exercise guarded archive compatibility on real managed simple-obfs build copies."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "wrt_core/managed"
RAW = SOURCES / "packages/simple-obfs"
COMPAT = ROOT / "wrt_core/simple_obfs_compat.py"
OLD_HASH = b"7a0154d2de18373e52783d1b64cf5204471049c2d2c64f0b3323d7f430aa4275"
ARCHIVE_HASH = b"da5af052265fbfba7a11ee4195257f9bc13f44d054d8fdcbace0639360870035"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def snapshot(directory):
    return {p.relative_to(directory).as_posix(): p.read_bytes()
            for p in directory.rglob("*") if p.is_file()}


def bash_path(path):
    value = Path(path).resolve().as_posix()
    return "/" + value[0].lower() + value[2:] if os.name == "nt" else value


class SimpleObfsCompatibility(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loader = load_module("managed_obfs_test", ROOT / "wrt_core/managed_plugins.py")

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="simple-obfs-compat-")
        self.addCleanup(temporary.cleanup)
        self.build = Path(temporary.name)
        self.package = self.build / "custom_feed/simple-obfs"
        self.loader.stage_package(SOURCES, "simple-obfs", self.package, self.build)
        self.recipe = self.package / "Makefile"

    def adapter(self):
        self.assertTrue(COMPAT.is_file(), "simple-obfs compatibility helper is not implemented")
        return load_module("simple_obfs_compat_test", COMPAT)

    def prepare(self):
        self.adapter().prepare(self.package)

    def assert_rejected_without_writes(self):
        before = snapshot(self.package)
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertEqual(snapshot(self.package), before)

    def test_real_staged_package_changes_only_hash_and_package_archive_format(self):
        original = snapshot(self.package)
        managed = snapshot(RAW)
        self.prepare()
        expected = dict(original)
        expected["Makefile"] = original["Makefile"].replace(
            b"PKG_MIRROR_HASH:=" + OLD_HASH + b"\n",
            b"PKG_MIRROR_HASH:=" + ARCHIVE_HASH + b"\nexport XZ_OPT := -T0\n")
        self.assertNotEqual(expected, original)
        self.assertEqual(snapshot(self.package), expected)
        self.assertEqual(snapshot(RAW), managed)

    def test_real_make_exports_fixed_archive_format_to_package_processes(self):
        # Parse the actual staged recipe with GNU Make and observe the child
        # process environment; the empty OpenWrt includes need no toolchain.
        (self.build / "rules.mk").write_bytes(b"")
        (self.build / "include").mkdir()
        (self.build / "include/package.mk").write_bytes(b"")
        (self.build / "unrelated.mk").write_bytes(b"PKG_NAME:=unrelated\n")
        (self.build / "probe.mk").write_text('''TOPDIR := .
INCLUDE_DIR := include
include $(PACKAGE_RECIPE)
.PHONY: probe
probe:
\t@printf '%s\\n' "$$XZ_OPT"
''', encoding="utf-8")
        make = os.environ.get("MAKE") or shutil.which("make")
        self.assertTrue(make, "GNU Make is required; use the repository test environment")
        environment = dict(os.environ, XZ_OPT="-T1")

        def observe(recipe):
            result = subprocess.run([make, "--no-print-directory", "-f", "probe.mk",
                                     "PACKAGE_RECIPE=" + recipe, "probe"], cwd=self.build,
                                    env=environment, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return result.stdout.strip()

        self.assertEqual(observe("custom_feed/simple-obfs/Makefile"), "-T1")
        self.prepare()
        self.assertEqual(observe("custom_feed/simple-obfs/Makefile"), "-T0")
        self.assertEqual(observe("unrelated.mk"), "-T1")

    def test_incomplete_or_changed_archive_format_is_rejected_without_writes(self):
        self.prepare()
        original = self.recipe.read_bytes()
        declaration = b"export XZ_OPT := -T0\n"
        self.assertIn(declaration, original)
        for changed in (b"", b"export XZ_OPT := -T1\n", b"export XZ_OPT := -T2\n",
                        declaration + b"export XZ_OPT := -T1\n"):
            with self.subTest(declaration=changed):
                self.recipe.write_bytes(original.replace(declaration, changed))
                self.assert_rejected_without_writes()

    def test_repeat_validates_without_rewriting_the_prepared_recipe(self):
        self.prepare()
        before = snapshot(self.package)
        stamp = self.recipe.stat().st_mtime_ns
        self.prepare()
        self.assertEqual(snapshot(self.package), before)
        self.assertEqual(self.recipe.stat().st_mtime_ns, stamp)

    def test_any_other_recipe_drift_is_rejected_before_and_after_preparation(self):
        mutations = (
            (b"PKG_SOURCE_PROTO:=git", b"PKG_SOURCE_PROTO:=https"),
            (b"shadowsocks/simple-obfs.git", b"other/simple-obfs.git"),
            (b"2019-08-17", b"2019-08-18"),
            (b"486bebd9208539058e57e23a12f23103016e09b4", b"0" * 40),
            (b"PKG_RELEASE:=2", b"PKG_RELEASE:=3"),
            (b"PKG_SOURCE_SUBDIR:=$(PKG_NAME)-$(PKG_VERSION)", b"PKG_SOURCE_SUBDIR:=other"),
            (b"PKG_FIXUP:=autoreconf", b"PKG_FIXUP:="),
        )
        for prepared in (False, True):
            self.loader.stage_package(SOURCES, "simple-obfs", self.package, self.build)
            if prepared:
                self.prepare()
            original = self.recipe.read_bytes()
            for old, new in mutations:
                with self.subTest(prepared=prepared, field=old):
                    self.assertIn(old, original)
                    self.recipe.write_bytes(original.replace(old, new))
                    self.assert_rejected_without_writes()
                    self.recipe.write_bytes(original)

    def test_unknown_or_duplicate_hash_cannot_bypass_the_guard(self):
        original = self.recipe.read_bytes()
        for changed in (
            original.replace(OLD_HASH, b"skip"),
            original.replace(OLD_HASH, b"0" * 64),
            original + b"\nPKG_MIRROR_HASH:=" + ARCHIVE_HASH + b"\n",
        ):
            with self.subTest(recipe=changed[-90:]):
                self.recipe.write_bytes(changed)
                self.assert_rejected_without_writes()

    def test_patch_drift_is_rechecked_on_original_and_prepared_packages(self):
        for prepared in (False, True):
            for mutation in ("missing", "modified", "extra"):
                with self.subTest(prepared=prepared, mutation=mutation):
                    self.loader.stage_package(SOURCES, "simple-obfs", self.package, self.build)
                    if prepared:
                        self.prepare()
                    patch = next((self.package / "patches").glob("*.patch"))
                    if mutation == "missing":
                        patch.unlink()
                    elif mutation == "modified":
                        patch.write_bytes(patch.read_bytes() + b"\n# drift\n")
                    else:
                        (patch.parent / "999-unreviewed.patch").write_bytes(b"unreviewed")
                    self.assert_rejected_without_writes()

    def test_extra_non_patch_file_is_rejected_without_partial_writes(self):
        (self.package / "unreviewed.mk").write_bytes(b"PKG_MIRROR_HASH:=skip\n")
        self.assert_rejected_without_writes()

    def test_missing_recipe_is_rejected_without_partial_writes(self):
        self.recipe.unlink()
        self.assert_rejected_without_writes()

    def test_managed_original_is_never_a_valid_destination(self):
        before = snapshot(RAW)
        with self.assertRaises(ValueError):
            self.adapter().prepare(RAW)
        self.assertEqual(snapshot(RAW), before)

    def test_cli_applies_to_real_build_copy_and_returns_failure_on_drift(self):
        result = subprocess.run([sys.executable, str(COMPAT), str(self.package)],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(b"PKG_MIRROR_HASH:=" + ARCHIVE_HASH + b"\n", self.recipe.read_bytes())
        self.recipe.write_bytes(self.recipe.read_bytes() + b"\n# drift\n")
        before = snapshot(self.package)
        result = subprocess.run([sys.executable, str(COMPAT), str(self.package)],
                                capture_output=True, text=True, timeout=20)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("simple-obfs", result.stderr)
        self.assertEqual(snapshot(self.package), before)

    def run_pre_install_stage(self):
        # Isolate unrelated network and platform hooks while executing the actual
        # production stage and its Python compatibility command against real files.
        script = '''set -euo pipefail
source "$BASE_PATH/update.sh"
while read -r _ _ name; do
    case "$name" in stage_pre_install_source_fixes) ;; *) eval "$name() { :; }" ;; esac
done < <(declare -F)
python3() { "$TEST_PYTHON" "$@"; }
get_custom_feed_worktree_dir() { printf '%s/custom_feed\\n' "$BUILD_DIR"; }
update_tcping() { touch "$BUILD_DIR/later-hook-reached"; }
stage_pre_install_source_fixes
'''
        environment = dict(os.environ, BASE_PATH=bash_path(ROOT / "wrt_core"),
                           BUILD_DIR=bash_path(self.build), TEST_PYTHON=Path(sys.executable).as_posix(),
                           PYTHONDONTWRITEBYTECODE="1")
        bash = os.environ.get("BASH") or shutil.which("bash") or "C:/Program Files/Git/bin/bash.exe"
        return subprocess.run([bash, "--noprofile", "--norc", "-c", script],
                              env=environment, capture_output=True, text=True, timeout=30)

    def test_production_pre_install_stage_applies_adapter_and_stops_on_drift(self):
        result = self.run_pre_install_stage()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(b"PKG_MIRROR_HASH:=" + ARCHIVE_HASH + b"\n", self.recipe.read_bytes())
        marker = self.build / "later-hook-reached"
        self.assertTrue(marker.exists())
        marker.unlink()
        self.recipe.write_bytes(self.recipe.read_bytes() + b"\n# drift\n")
        before = snapshot(self.package)
        result = self.run_pre_install_stage()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(marker.exists())
        self.assertEqual(snapshot(self.package), before)


if __name__ == "__main__":
    unittest.main()
