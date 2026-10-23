#!/usr/bin/env python3
"""Exercise ordered ADG source preparation, with no installed service access."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/plugin-runtime"
FILES = {
    "root/usr/share/AdGuardHome/update_core.sh": "adguard-updater.sh",
    "root/usr/share/AdGuardHome/links.txt": "adguard-links.txt",
    "luasrc/controller/AdGuardHome.lua": "AdGuardHome.lua",
}
PATCHES = ("adguardhome-update-safety.patch", "adguardhome-noop-update.patch")
BASH = shutil.which("bash") or r"C:\Program Files\Git\bin\bash.exe"


def snapshot(package):
    return {str(path.relative_to(package)): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in package.rglob("*") if path.is_file() and ".git" not in path.relative_to(package).parts}


class AdguardSourcePreparation(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="adg-source-compat-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.package = self.directory / "source/luci-app-adguardhome"
        self.make_package(self.package)

    def make_package(self, package):
        for target, fixture in FILES.items():
            path = package / target
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(FIXTURES / fixture, path)
        # Deliberately retained, mutable user content outside the program guards.
        config = package / "root/etc/config/AdGuardHome"
        config.parent.mkdir(parents=True)
        config.write_bytes(b"config AdGuardHome 'AdGuardHome'\n option enabled '1'\n option port '5553'\n")
        (package / "unrelated.txt").write_bytes(b"preserve upstream other content\n")
        subprocess.run(["git", "-C", str(package), "init", "-q"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(package), "config", "core.autocrlf", "false"], check=True)

    def apply(self, package, patch):
        result = subprocess.run(["git", "-C", str(package), "apply", str(ROOT / "wrt_core/patches" / patch)],
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def prepare(self, package=None, base=None):
        env = os.environ.copy()
        env["BASE_PATH"] = (base or ROOT / "wrt_core").as_posix()
        env["ADG_SOURCE_PACKAGE"] = (package or self.package).as_posix()
        return subprocess.run([BASH, "--noprofile", "--norc", "-c",
                               '. "$1"; fix_adguardhome_compat "$ADG_SOURCE_PACKAGE"',
                               "adg-source-test", (ROOT / "wrt_core/modules/plugin_compat.sh").as_posix()],
                              env=env, capture_output=True, text=True, encoding="utf-8", timeout=120)

    def test_all_complete_patch_subsets_converge_and_repeat_without_touching_user_config(self):
        reference = self.directory / "expected"
        self.make_package(reference)
        for patch in PATCHES:
            self.apply(reference, patch)
        expected = {target: (reference / target).read_bytes() for target in FILES}
        for mask in range(4):
            with self.subTest(mask=mask):
                package = self.directory / ("subset-" + str(mask))
                self.make_package(package)
                for index, patch in enumerate(PATCHES):
                    if mask & (1 << index):
                        self.apply(package, patch)
                retained = package / "root/etc/config/AdGuardHome"
                before = retained.read_bytes(), retained.stat().st_mtime_ns
                result = self.prepare(package)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                for target, data in expected.items():
                    self.assertEqual((package / target).read_bytes(), data, target)
                self.assertEqual((retained.read_bytes(), retained.stat().st_mtime_ns), before)
                first = snapshot(package)
                result = self.prepare(package)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(snapshot(package), first, "repeat changed program or user content")

    def test_unreviewed_source_drift_rejects_before_any_real_write(self):
        for index, target in enumerate(FILES):
            with self.subTest(target=target):
                package = self.directory / ("drift-" + str(index))
                self.make_package(package)
                with (package / target).open("ab") as stream:
                    stream.write(b"\n# unreviewed addition outside patch context\n")
                before = snapshot(package)
                result = self.prepare(package)
                self.assertNotEqual(result.returncode, 0, "unreviewed source was accepted")
                self.assertEqual(snapshot(package), before, "rejection partially changed package")

    def test_incomplete_old_patch_rejects_without_publishing_other_program_changes(self):
        self.apply(self.package, PATCHES[0])
        target = "luasrc/controller/AdGuardHome.lua"
        shutil.copyfile(FIXTURES / FILES[target], self.package / target)
        before = snapshot(self.package)
        result = self.prepare()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(snapshot(self.package), before)

    def test_missing_patch_or_table_rejects_before_any_write(self):
        for missing in ("patches/adguardhome-noop-update.patch", "compat/adguardhome/source-files.tsv"):
            with self.subTest(missing=missing):
                tools = self.directory / ("tools-" + Path(missing).name)
                for patch in PATCHES:
                    path = tools / "patches" / patch
                    path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(ROOT / "wrt_core/patches" / patch, path)
                table = tools / "compat/adguardhome/source-files.tsv"
                table.parent.mkdir(parents=True)
                shutil.copyfile(ROOT / "wrt_core/compat/adguardhome/source-files.tsv", table)
                (tools / missing).unlink()
                before = snapshot(self.package)
                result = self.prepare(base=tools)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(snapshot(self.package), before)


if __name__ == "__main__":
    unittest.main()
