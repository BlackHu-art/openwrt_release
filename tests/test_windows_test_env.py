#!/usr/bin/env python3
"""Offline contracts for the Windows dependency installer and regression runner."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import socket
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import windows_test_env as tooling


# Match the installer's native tar boundary. Git's GNU tar interprets a Windows
# drive prefix as a remote host when called directly by native Python.
TAR = str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/tar.exe") if os.name == "nt" else shutil.which("tar")


class WindowsTestEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="windows tooling ")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)

    def test_download_rejects_wrong_hash_without_replacing_existing_file(self):
        target = self.base / "cached archive"
        target.write_bytes(b"previous verified archive")
        with patch.object(tooling.urllib.request, "urlopen", return_value=io.BytesIO(b"bad download")):
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                tooling.download_verified("https://example.invalid/package", target, "0" * 64)
        self.assertEqual(target.read_bytes(), b"previous verified archive")

    def test_download_rejects_oversize_response(self):
        target = self.base / "archive"
        with patch.object(tooling.urllib.request, "urlopen", return_value=io.BytesIO(b"oversized")):
            with patch.object(tooling, "MAX_DOWNLOAD_BYTES", 4):
                with self.assertRaisesRegex(ValueError, "budget"):
                    tooling.download_verified("https://example.invalid/package", target, "0" * 64)
        self.assertFalse(target.exists())

    def test_verified_download_writes_exact_bytes(self):
        data = b"fixed release bytes"
        target = self.base / "archive"
        with patch.object(tooling.urllib.request, "urlopen", return_value=io.BytesIO(data)):
            tooling.download_verified("https://example.invalid/package", target, hashlib.sha256(data).hexdigest())
        self.assertEqual(target.read_bytes(), data)

    def make_archive(self, executable):
        archive = self.base / "package.tar"
        with tarfile.open(archive, "w") as output:
            for name, data in [("usr/bin/flock.exe", executable), ("../unexpected.txt", b"unwanted")]:
                entry = tarfile.TarInfo(name)
                entry.size = len(data)
                output.addfile(entry, io.BytesIO(data))
        return archive

    def test_extract_reads_only_exact_member_even_with_traversal_companion(self):
        data = b"fixture executable bytes"
        archive = self.make_archive(data)
        target = self.base / "installed" / "flock.exe"
        with patch.object(tooling, "FLOCK_EXE_SHA256", hashlib.sha256(data).hexdigest()):
            tooling.extract_flock(archive, TAR, target)
        self.assertEqual(target.read_bytes(), data)
        self.assertEqual({p.name for p in self.base.iterdir()}, {"installed", "package.tar"})
        self.assertFalse((self.base.parent / "unexpected.txt").exists())

    def test_extract_hash_failure_preserves_installed_executable(self):
        archive = self.make_archive(b"corrupt executable")
        target = self.base / "flock.exe"
        target.write_bytes(b"working installation")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            tooling.extract_flock(archive, TAR, target)
        self.assertEqual(target.read_bytes(), b"working installation")

    def test_cached_executable_must_match_pinned_bytes(self):
        target = self.base / "xray.exe"
        data = b"pinned executable"
        target.write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        self.assertTrue(tooling.matches_hash(target, digest))
        target.write_bytes(b"unexpected new version")
        self.assertFalse(tooling.matches_hash(target, digest))

    def test_child_environment_is_isolated_and_uses_selected_dependencies(self):
        layout = tooling.Layout(self.base / "repository", self.base / "dependencies", self.base / "Git")
        inherited = {"PATH": "existing", "PYTHONPATH": "injected", "PYTHONHOME": "other python", "KEEP": "yes"}
        environment = tooling.child_environment(layout, inherited)
        self.assertEqual(inherited["PYTHONPATH"], "injected")
        self.assertNotIn("PYTHONPATH", environment)
        self.assertNotIn("PYTHONHOME", environment)
        self.assertEqual(environment["KEEP"], "yes")
        self.assertEqual(environment["PATH"].split(os.pathsep)[:4], [
            str(layout.python.parent), str(layout.flock.parent),
            str(layout.git / "bin"), str(layout.git / "usr/bin")])
        self.assertEqual(environment["SSRP_TEST_FLOCK_DIR"], str(layout.flock.parent))
        self.assertEqual(environment["XRAY_TEST_BINARY"], str(layout.xray))
        self.assertEqual(environment["PYTHONDONTWRITEBYTECODE"], "1")

    def test_dependencies_cannot_be_placed_in_repository(self):
        repository = self.base / "repository"
        for directory in (repository, repository / "cache"):
            with self.assertRaisesRegex(ValueError, "outside"):
                tooling.validate_dependency_location(repository, directory)
        tooling.validate_dependency_location(repository, self.base / "dependencies")

    def test_run_records_full_output_and_preserves_failure_code_with_spaced_paths(self):
        script = self.base / "child script.py"
        script.write_text("import sys\nprint('stdout evidence', flush=True)\nprint('stderr evidence', file=sys.stderr)\nsys.exit(7)\n")
        run_dir = self.base / "run log"
        command = [sys.executable, str(script)]
        with contextlib.redirect_stdout(io.StringIO()):
            code = tooling.run_logged(command, self.base, os.environ.copy(), run_dir, {"purpose": "contract"})
        self.assertEqual(code, 7)
        log = (run_dir / "regression.log").read_text(encoding="utf-8")
        self.assertIn("stdout evidence", log)
        self.assertIn("stderr evidence", log)
        result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(result["exit_code"], 7)
        self.assertEqual(result["command"], command)
        self.assertEqual(result["purpose"], "contract")
        self.assertTrue(result["finished_at"])

    def test_launch_failure_is_recorded_as_failure(self):
        run_dir = self.base / "launch failure"
        with contextlib.redirect_stdout(io.StringIO()):
            code = tooling.run_logged([str(self.base / "absent.exe")], self.base, os.environ.copy(), run_dir, {})
        self.assertNotEqual(code, 0)
        result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(result["exit_code"], code)
        self.assertIn("error", result)

    def test_interrupt_stops_the_regression_process_tree(self):
        # A connected socket stays open while the real grandchild is alive.
        # Closing it in finally also releases the fixture if this assertion fails.
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            listener.settimeout(5)
            grandchild = self.base / "grandchild.py"
            grandchild.write_text(
                "import socket,sys\n"
                "with socket.create_connection(('127.0.0.1', int(sys.argv[1])), timeout=10) as connection:\n"
                "    connection.sendall(b'R')\n"
                "    print('cancel-ready', flush=True)\n"
                "    connection.recv(1)\n", encoding="utf-8")
            parent = self.base / "parent.py"
            parent.write_text(
                "import os,subprocess,sys,time\n"
                "subprocess.Popen([sys.executable, sys.argv[1], sys.argv[2]], cwd=os.path.dirname(sys.executable))\n"
                "time.sleep(10)\n", encoding="utf-8")
            connections = []

            def interrupt_when_ready(*args, **kwargs):
                if args and str(args[0]).strip() == "cancel-ready":
                    connection, _ = listener.accept()
                    connections.append(connection)
                    connection.settimeout(3)
                    self.assertEqual(connection.recv(1), b"R")
                    raise KeyboardInterrupt

            run_dir = self.base / "interrupted run"
            try:
                with patch.object(tooling, "print", side_effect=interrupt_when_ready, create=True):
                    code = tooling.run_logged(
                        [sys.executable, str(parent), str(grandchild), str(listener.getsockname()[1])],
                        self.base, os.environ.copy(), run_dir, {})
                self.assertEqual(code, 130)
                self.assertEqual(len(connections), 1)
                try:
                    self.assertEqual(connections[0].recv(1), b"")
                except ConnectionResetError:
                    pass  # Windows may reset the socket when taskkill ends its owner.
                except TimeoutError:
                    self.fail("grandchild remained alive after regression cancellation")
                result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
                self.assertEqual(result["exit_code"], 130)
                self.assertEqual(result["error"], "interrupted")
                self.assertNotIn("cleanup_error", result)
            finally:
                for connection in connections:
                    connection.close()


if __name__ == "__main__":
    unittest.main()
