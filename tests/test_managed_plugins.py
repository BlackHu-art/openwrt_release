#!/usr/bin/env python3
"""Check build-owned sources and their filesystem materialization contract."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "wrt_core/managed_plugins.py"


class ManagedPackages(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("managed_plugins", SCRIPT)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.temp = tempfile.TemporaryDirectory(prefix="managed-plugins-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sources = self.root / "sources"
        self.package = self.sources / "packages/example"
        self.package.mkdir(parents=True)
        self.files = {"Makefile": (b"PKG_NAME:=example\n", "100644"),
                      "root/etc/config/example": (b"option enabled '0'\n", "100644"),
                      "root/etc/init.d/example": (b"#!/bin/sh\nexit 0\n", "100755")}
        self.build = self.root / "build"
        self.target = self.build / "custom_feed/example"
        self.write_sources()

    def write_sources(self):
        files = []
        for name, (content, mode) in self.files.items():
            path = self.package / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            files.append({"path": name, "mode": mode,
                          "sha256": hashlib.sha256(content).hexdigest()})
        self.lock = {"schema_version": 1, "packages": {"example": {
            "path": "packages/example", "files": files}}}
        (self.sources / "sources.lock.json").write_text(json.dumps(self.lock), encoding="utf-8")

    def stage(self):
        self.module.stage_package(self.sources, "example", self.target, self.build)

    def test_stages_exact_bytes_without_touching_runtime_config(self):
        runtime = self.build / "files/etc/config/example"
        runtime.parent.mkdir(parents=True)
        runtime.write_bytes(b"user custom settings\n")
        before = {p.relative_to(self.sources): p.read_bytes()
                  for p in self.sources.rglob("*") if p.is_file()}
        self.stage()
        for name, (content, _) in self.files.items():
            self.assertEqual((self.target / name).read_bytes(), content)
        self.assertEqual(runtime.read_bytes(), b"user custom settings\n")
        (self.target / "stale-upstream-file").write_text("stale", encoding="utf-8")
        self.stage()
        self.assertFalse((self.target / "stale-upstream-file").exists())
        self.assertEqual(before, {p.relative_to(self.sources): p.read_bytes()
                                  for p in self.sources.rglob("*") if p.is_file()})

    @unittest.skipIf(os.name == "nt", "POSIX executable modes are checked in Linux CI")
    def test_restores_source_executable_modes(self):
        self.stage()
        self.assertEqual(stat.S_IMODE((self.target / "root/etc/init.d/example").stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE((self.target / "Makefile").stat().st_mode), 0o644)

    def test_tampered_missing_or_extra_sources_preserve_existing_destination(self):
        for mutation in ("tampered", "missing", "extra"):
            with self.subTest(mutation=mutation):
                self.write_sources()
                self.target.mkdir(parents=True, exist_ok=True)
                keep = self.target / "keep"
                keep.write_bytes(b"existing source")
                if mutation == "tampered":
                    (self.package / "Makefile").write_bytes(b"changed")
                elif mutation == "missing":
                    (self.package / "Makefile").unlink()
                else:
                    (self.package / "untracked").write_bytes(b"extra")
                with self.assertRaises(ValueError):
                    self.stage()
                self.assertEqual(keep.read_bytes(), b"existing source")
                if (self.package / "untracked").exists():
                    (self.package / "untracked").unlink()

    def test_refuses_destination_outside_build_and_build_root_itself(self):
        for target in (self.root / "user-data", self.build):
            with self.subTest(target=target), self.assertRaises(ValueError):
                self.module.stage_package(self.sources, "example", target, self.build)

    def test_rejects_manifest_traversal_before_creating_destination(self):
        self.lock["packages"]["example"]["files"][0]["path"] = "../outside"
        (self.sources / "sources.lock.json").write_text(json.dumps(self.lock), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.stage()
        self.assertFalse(self.target.exists())

    @unittest.skipIf(os.name == "nt", "real symlink creation is checked in Linux CI")
    def test_materializes_recorded_relative_symlink(self):
        self.files["translation"] = (b"root/etc/config/example", "120000")
        self.write_sources()
        self.stage()
        self.assertTrue((self.target / "translation").is_symlink())
        self.assertEqual(os.readlink(self.target / "translation"), "root/etc/config/example")
        self.assertEqual((self.target / "translation").read_bytes(), self.files["root/etc/config/example"][0])

    def test_unknown_package_has_no_network_or_destination_side_effect(self):
        with self.assertRaises(ValueError):
            self.module.stage_package(self.sources, "missing", self.target, self.build)
        self.assertFalse(self.target.exists())


if __name__ == "__main__":
    unittest.main()
