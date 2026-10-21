#!/usr/bin/env python3
"""Exercise the artifact CLI against synthetic roots and real package containers."""
import copy
import gzip
import hashlib
import io
import json
from pathlib import Path
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "wrt_core/ssrplus_verify.py"
MANIFEST_TARGET = "usr/share/shadowsocksr/ssrplus-build.json"
PROTECTED = "etc/init.d/shadowsocksr"
CONTENT = b"#!/bin/sh\necho repaired\n"


def tar_bytes(files):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        for name, content, mode in files:
            entry = tarfile.TarInfo(name)
            entry.size, entry.mode = len(content), mode
            archive.addfile(entry, io.BytesIO(content))
    return stream.getvalue()


def ar_bytes(files):
    output = bytearray(b"!<arch>\n")
    for name, content in files:
        header = f"{name + '/':<16}{0:<12}{0:<6}{0:<6}{0o100644:<8o}{len(content):<10}`\n"
        output.extend(header.encode())
        output.extend(content)
        if len(content) % 2:
            output.extend(b"\n")
    return output


class ArtifactVerification(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ssr-artifact-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "rootfs"
        target = self.root / PROTECTED
        target.parent.mkdir(parents=True)
        target.write_bytes(CONTENT)
        target.chmod(0o755)
        self.mode = stat.S_IMODE(target.stat().st_mode)
        self.manifest = {
            "source_commit": "2abdc9aa9e19607774dc9789709212b70b8607c6",
            "repair_version": "190-r5",
            "patches": {"ssrplus-example.patch": "a" * 64},
            "files": {"/" + PROTECTED: {"sha256": hashlib.sha256(CONTENT).hexdigest(),
                                       "mode": f"{self.mode:04o}"}},
        }
        self.expected = self.base / "expected.json"
        self.write_expected()
        self.write_embedded()

    def write_expected(self):
        self.expected.write_text(json.dumps(self.manifest), encoding="utf-8")

    def write_embedded(self, value=None):
        target = self.root / MANIFEST_TARGET
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.manifest if value is None else value), encoding="utf-8")

    def cli(self, *arguments, success=True):
        result = subprocess.run([sys.executable, str(CLI), *map(str, arguments)],
                                capture_output=True, text=True, timeout=30)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("SSR artifact verification failed:", result.stderr)
        return result

    def make_package(self, kind="ar", *, data=None, version="190-5", embedded=None, name="luci-app-ssr-plus"):
        if data is None:
            data = [(PROTECTED, CONTENT, self.mode)]
        manifest = json.dumps(self.manifest if embedded is None else embedded).encode()
        payload = gzip.compress(tar_bytes([*data, (MANIFEST_TARGET, manifest, 0o644)]))
        control = f"Package: {name}\nVersion: {version}\nArchitecture: all\n".encode()
        control_tar = gzip.compress(tar_bytes([("control", control, 0o644)]))
        path = self.base / ("compiled.apk" if kind == "apk2" else "compiled.ipk")
        if kind == "ar":
            path.write_bytes(ar_bytes([("debian-binary", b"2.0\n"), ("control.tar.gz", control_tar),
                                       ("data.tar.gz", payload)]))
        elif kind == "tar":
            path.write_bytes(gzip.compress(tar_bytes([("./debian-binary", b"2.0\n", 0o644),
                                                      ("./control.tar.gz", control_tar, 0o644),
                                                      ("./data.tar.gz", payload, 0o644)])))
        else:
            package_info = f"pkgname = {name}\npkgver = {version}\narch = all\n".encode()
            path.write_bytes(gzip.compress(tar_bytes([(".SIGN.RSA.fixture", b"signature", 0o644)])) +
                             gzip.compress(tar_bytes([(".PKGINFO", package_info, 0o644)])) + payload)
        return path

    def test_rootfs_matches_expected_files_and_embedded_fix_identity(self):
        self.cli("rootfs", "--manifest", self.expected, "--root", self.root)

    def test_missing_rootfs_protected_file_fails(self):
        (self.root / PROTECTED).unlink()
        self.cli("rootfs", "--manifest", self.expected, "--root", self.root, success=False)

    def test_changed_rootfs_bytes_fail(self):
        (self.root / PROTECTED).write_bytes(b"old cached init script\n")
        self.cli("rootfs", "--manifest", self.expected, "--root", self.root, success=False)

    def test_changed_rootfs_mode_fails(self):
        self.manifest["files"]["/" + PROTECTED]["mode"] = "0777" if self.mode != 0o777 else "0600"
        self.write_expected()
        self.write_embedded()
        self.cli("rootfs", "--manifest", self.expected, "--root", self.root, success=False)

    def test_missing_embedded_manifest_fails(self):
        (self.root / MANIFEST_TARGET).unlink()
        self.cli("rootfs", "--manifest", self.expected, "--root", self.root, success=False)

    def test_stale_embedded_patch_identity_fails(self):
        stale = copy.deepcopy(self.manifest)
        stale["patches"]["ssrplus-example.patch"] = "b" * 64
        self.write_embedded(stale)
        self.cli("rootfs", "--manifest", self.expected, "--root", self.root, success=False)

    def test_parent_traversal_in_manifest_fails_without_reading_outside_root(self):
        self.manifest["files"]["/../outside"] = self.manifest["files"].pop("/" + PROTECTED)
        self.write_expected()
        self.cli("rootfs", "--manifest", self.expected, "--root", self.root, success=False)

    def test_empty_manifest_cannot_bypass_payload_verification(self):
        self.manifest["files"] = {}
        self.write_expected()
        self.write_embedded()
        self.cli("rootfs", "--manifest", self.expected, "--root", self.root, success=False)

    def test_ar_ipk_verifies_actual_payload_and_control_metadata(self):
        self.cli("package", "--manifest", self.expected, "--package", self.make_package())

    def test_openwrt_tar_ipk_verifies_actual_payload(self):
        self.cli("package", "--manifest", self.expected, "--package", self.make_package("tar"))

    def test_apk_v2_reads_payload_after_signature_and_control_gzip_streams(self):
        self.cli("package", "--manifest", self.expected, "--package",
                 self.make_package("apk2", version="190-r5"))

    def test_package_missing_protected_file_fails(self):
        self.cli("package", "--manifest", self.expected, "--package", self.make_package(data=[]), success=False)

    def test_package_changed_file_bytes_fail(self):
        package = self.make_package(data=[(PROTECTED, b"unpatched\n", self.mode)])
        self.cli("package", "--manifest", self.expected, "--package", package, success=False)

    def test_package_changed_mode_fails(self):
        package = self.make_package(data=[(PROTECTED, CONTENT, self.mode ^ 0o100)])
        self.cli("package", "--manifest", self.expected, "--package", package, success=False)

    def test_archive_executable_mode_is_checked_independently_of_host_permissions(self):
        self.manifest["files"]["/" + PROTECTED]["mode"] = "0755"
        self.write_expected()
        executable = self.make_package(data=[(PROTECTED, CONTENT, 0o755)])
        self.cli("package", "--manifest", self.expected, "--package", executable)
        stripped = self.make_package(data=[(PROTECTED, CONTENT, 0o644)])
        self.cli("package", "--manifest", self.expected, "--package", stripped, success=False)

    def test_package_embedded_repair_identity_must_match_trusted_source(self):
        stale = copy.deepcopy(self.manifest)
        stale["repair_version"] = "190-r3"
        self.cli("package", "--manifest", self.expected, "--package",
                 self.make_package(embedded=stale), success=False)

    def test_manifest_requires_a_real_repair_version_string(self):
        self.manifest["repair_version"] = None
        self.write_expected()
        self.write_embedded()
        self.cli("rootfs", "--manifest", self.expected, "--root", self.root, success=False)

    def test_duplicate_protected_payload_member_fails(self):
        package = self.make_package(data=[(PROTECTED, CONTENT, self.mode), (PROTECTED, CONTENT, self.mode)])
        self.cli("package", "--manifest", self.expected, "--package", package, success=False)

    def test_old_package_control_version_fails_even_with_repaired_bytes(self):
        for version in ("190-3", "190-4", "190-r4"):
            with self.subTest(version=version):
                self.cli("package", "--manifest", self.expected, "--package",
                         self.make_package(version=version), success=False)

    def test_wrong_package_name_fails(self):
        self.cli("package", "--manifest", self.expected, "--package",
                 self.make_package(name="another-package"), success=False)

    def test_v3_apk_without_native_tool_fails_with_actionable_diagnostic(self):
        package = self.base / "new.apk"
        package.write_bytes(b"ADB." + b"unsupported fixture")
        result = self.cli("package", "--manifest", self.expected, "--package", package, success=False)
        self.assertIn("--apk-tool", result.stderr)

    def test_manifest_command_hashes_files_patch_bytes_and_modes(self):
        patch = self.base / "ssrplus-fixture.patch"
        patch.write_bytes(b"source repair\n")
        output = self.base / "generated.json"
        self.cli("manifest", "--root", self.root, "--output", output,
                 "--source-commit", self.manifest["source_commit"], "--repair-version", "190-r5",
                 "--patch", patch, "--file", "/" + PROTECTED)
        result = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(result["files"], self.manifest["files"])
        self.assertEqual(result["patches"], {patch.name: hashlib.sha256(b"source repair\n").hexdigest()})
        self.assertEqual(result["repair_version"], "190-r5")


class WorkflowGates(unittest.TestCase):
    def read_workflow(self, name):
        return yaml.safe_load((ROOT / ".github/workflows" / name).read_text(encoding="utf-8"))

    def test_build_and_release_wait_for_reusable_regression_and_linux_gate(self):
        for name in ("build_wrt.yml", "release_wrt.yml"):
            with self.subTest(workflow=name):
                workflow = self.read_workflow(name)
                jobs = workflow["jobs"]
                gate = jobs.get("ssrplus-gate", {})
                self.assertEqual(gate.get("uses"), "./.github/workflows/test_ssrplus.yml")
                dependencies = jobs["build"].get("needs", [])
                if isinstance(dependencies, str):
                    dependencies = [dependencies]
                self.assertIn("ssrplus-gate", dependencies)
                self.assertNotIn("always()", jobs["build"].get("if", ""))

    def test_regression_gate_is_callable_and_installs_real_lua51(self):
        workflow = self.read_workflow("test_ssrplus.yml")
        triggers = workflow.get("on", workflow.get(True, {}))
        self.assertIn("workflow_call", triggers)
        scripts = "\n".join(step.get("run", "") for step in workflow["jobs"]["regression"]["steps"])
        self.assertIn("-m venv", scripts)
        self.assertIn("pip install -r tests/requirements.txt", scripts)
        self.assertIn("from lupa.lua51 import LuaRuntime", scripts)
        self.assertIn("Lua 5.1", scripts)
        self.assertIn("sudo unshare -n bash tests/test_ssrplus_linux.sh", scripts)

    def test_all_models_release_inherits_callee_gate(self):
        workflow = self.read_workflow("release_wrt_all.yml")
        self.assertEqual(workflow["jobs"]["release"]["uses"], "./.github/workflows/release_wrt.yml")
        release = self.read_workflow("release_wrt.yml")
        self.assertEqual(release["jobs"]["build"].get("needs"), "ssrplus-gate")


if __name__ == "__main__":
    unittest.main()
