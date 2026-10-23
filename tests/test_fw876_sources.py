#!/usr/bin/env python3
"""Check the selected fw876 source boundary against the captured Git manifest."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "wrt_core/managed"
SNAPSHOT = ROOT / "maintenance/plugins/ssrplus/upstream-v198.2"
COMMIT = "45893d778767f3bdb2fcb6e873cf8f9a667d94d4"
PACKAGES = {
    "luci-app-ssr-plus", "xray-core", "chinadns-ng", "dns2socks", "dns2tcp",
    "lua-neturl", "microsocks", "mosdns", "shadowsocks-rust", "shadowsocksr-libev",
    "simple-obfs", "tcping", "v2ray-plugin", "ipt2socks", "upx",
}


class Fw876Sources(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("managed_plugins", ROOT / "wrt_core/managed_plugins.py")
        cls.loader = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.loader)

    def test_locked_files_survive_normal_git_add(self):
        lock = self.loader.read_lock(SOURCES)
        paths = ["wrt_core/managed/packages/" + name + "/" + item["path"]
                 for name in PACKAGES for item in lock["packages"][name]["files"]]
        result = subprocess.run(["git", "check-ignore", "--no-index", "-z", "--stdin"],
            input=("\0".join(paths) + "\0").encode(), capture_output=True, cwd=ROOT)
        self.assertIn(result.returncode, (0, 1), result.stderr.decode())
        self.assertEqual(result.stdout, b"", "locked source would be omitted from a normal commit")

    def test_selected_packages_reproduce_the_complete_pinned_upstream_blobs(self):
        lock = self.loader.read_lock(SOURCES)
        imported = {name for name, package in lock["packages"].items()
                    if package["repository"].removesuffix(".git") == "https://github.com/fw876/helloworld"}
        self.assertEqual(imported, PACKAGES)
        manifest = json.loads((ROOT / "maintenance/plugins/manifests/ssrplus-v198.2.json").read_text())
        self.assertEqual(manifest["commit"], COMMIT)
        for name in sorted(PACKAGES):
            with self.subTest(package=name):
                package, files = self.loader.verify_package(SOURCES, name)
                self.assertEqual(lock["packages"][name]["commit"], COMMIT)
                expected = {item["path"].removeprefix(name + "/"): item
                            for item in manifest["files"] if item["path"].startswith(name + "/")}
                self.assertEqual(set(files), set(expected))
                for relative, captured in expected.items():
                    self.assertEqual(files[relative]["mode"], captured["git_mode"])
                    self.assertEqual(files[relative]["sha256"], captured["sha256"])
                    self.assertEqual(files[relative]["git_blob"], captured["git_blob"])
                    self.assertEqual((package / relative).read_bytes(), (SNAPSHOT / captured["path"]).read_bytes())

    def test_staged_xray_has_all_ten_private_protocol_patches_and_is_repeatable(self):
        with tempfile.TemporaryDirectory(prefix="fw876-stage-") as temporary:
            build = Path(temporary)
            target = build / "custom_feed/xray-core"
            self.loader.stage_package(SOURCES, "xray-core", target, build)
            patches = sorted(target.glob("patches/*.patch"))
            self.assertEqual(len(patches), 10)
            expected = {p.relative_to(target).as_posix(): p.read_bytes() for p in target.rglob("*") if p.is_file()}
            (target / "patches/unreviewed.patch").write_bytes(b"unexpected patch")
            self.loader.stage_package(SOURCES, "xray-core", target, build)
            actual = {p.relative_to(target).as_posix(): p.read_bytes() for p in target.rglob("*") if p.is_file()}
            self.assertEqual(actual, expected)

    def test_source_license_is_preserved_and_verified(self):
        lock = self.loader.read_lock(SOURCES)
        license_path = SOURCES / "licenses/fw876_helloworld/LICENSE"
        self.assertTrue(license_path.is_file())
        self.assertEqual(license_path.read_bytes(), (SNAPSHOT / "LICENSE").read_bytes())
        captured = [item for item in lock["supplemental_files"]
                    if item["path"] == "licenses/fw876_helloworld/LICENSE"]
        self.assertEqual(len(captured), 1)
        self.assertEqual(hashlib.sha256(license_path.read_bytes()).hexdigest(), captured[0]["sha256"])


if __name__ == "__main__":
    unittest.main()
