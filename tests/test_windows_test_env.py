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
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import windows_test_env as tooling


# Match the installer's native tar boundary. Git's GNU tar interprets a Windows
# drive prefix as a remote host when called directly by native Python.
TAR = str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/tar.exe") if os.name == "nt" else shutil.which("tar")
RUBY_FIXTURE_SHA256 = "c766f8b523161435fe3fd02fd9d0a8af7af271edda62187f1c6b468a0836241a"


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

    @unittest.skipUnless(os.name == "nt", "Windows executable staging contract")
    def test_atomic_executable_preserves_msys_fork_after_replacement(self):
        source_directory = os.environ.get("SSRP_TEST_FLOCK_DIR")
        if not source_directory:
            self.skipTest("the managed Windows runner supplies its verified flock for the native fork contract")
        source = Path(source_directory) / "flock.exe"
        self.assertTrue(tooling.matches_hash(source, tooling.FLOCK_EXE_SHA256))
        target = self.base / "managed/usr/bin/flock.exe"
        tooling.atomic_write(target, source.read_bytes())
        environment = dict(os.environ, PATH=str(tooling.GIT_ROOT / "usr/bin") + os.pathsep + os.environ.get("PATH", ""))
        result = subprocess.run([str(target), "-n", "/dev/null", "true"],
                                env=environment, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(tooling.sha256(target), tooling.sha256(source))

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

    def make_ruby_archive(self, extra=None):
        archive = self.base / "ruby.tar"
        members = [("bin/ruby.exe", b"ruby executable"), ("lib/yaml.rb", b"YAML fixture"),
                   ("include/ruby.h", b"unused build headers")]
        if extra:
            members.append(extra)
        with tarfile.open(archive, "w") as output:
            for name, data in members:
                entry = tarfile.TarInfo("rubyinstaller-3.4.9-1-x64/" + name)
                entry.size = len(data)
                output.addfile(entry, io.BytesIO(data))
        return archive

    def test_ruby_extraction_installs_complete_runtime_and_replaces_corrupt_files(self):
        archive = self.make_ruby_archive()
        target = self.base / "ruby runtime"
        target.mkdir()
        (target / "corrupt.txt").write_bytes(b"stale runtime file")
        with patch.object(tooling, "RUBY_RUNTIME_SHA256", RUBY_FIXTURE_SHA256, create=True):
            tooling.extract_ruby(archive, TAR, target)
        self.assertEqual((target / "bin/ruby.exe").read_bytes(), b"ruby executable")
        self.assertEqual((target / "lib/yaml.rb").read_bytes(), b"YAML fixture")
        self.assertFalse((target / "include").exists())
        self.assertFalse((target / "corrupt.txt").exists())
        self.assertEqual(tooling.tree_sha256(target), RUBY_FIXTURE_SHA256)

    def test_ruby_extraction_hash_failure_preserves_installed_runtime(self):
        archive = self.make_ruby_archive()
        target = self.base / "ruby runtime"
        target.mkdir()
        (target / "previous").write_bytes(b"working runtime")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            tooling.extract_ruby(archive, TAR, target)
        self.assertEqual((target / "previous").read_bytes(), b"working runtime")
        self.assertFalse((target / "bin").exists())

    def test_ruby_extraction_rejects_traversal_before_writing_files(self):
        archive = self.make_ruby_archive(("lib/../../escaped.txt", b"unwanted"))
        target = self.base / "ruby runtime"
        with self.assertRaisesRegex(ValueError, "archive path"):
            tooling.extract_ruby(archive, TAR, target)
        self.assertFalse(target.exists())
        self.assertFalse((self.base / "escaped.txt").exists())

    def test_ruby_runtime_digest_detects_changed_missing_and_extra_libraries(self):
        runtime = self.base / "ruby"
        (runtime / "bin").mkdir(parents=True)
        (runtime / "lib").mkdir()
        (runtime / "bin/ruby.exe").write_bytes(b"ruby executable")
        library = runtime / "lib/yaml.rb"
        library.write_bytes(b"YAML fixture")
        self.assertEqual(tooling.tree_sha256(runtime), RUBY_FIXTURE_SHA256)
        library.write_bytes(b"injected library")
        self.assertNotEqual(tooling.tree_sha256(runtime), RUBY_FIXTURE_SHA256)
        library.unlink()
        self.assertNotEqual(tooling.tree_sha256(runtime), RUBY_FIXTURE_SHA256)
        library.write_bytes(b"YAML fixture")
        (runtime / "lib/unexpected.rb").write_bytes(b"injected library")
        self.assertNotEqual(tooling.tree_sha256(runtime), RUBY_FIXTURE_SHA256)

    def test_node_extraction_reads_only_pinned_executable(self):
        archive = self.base / "node.zip"
        data = b"node executable"
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("node-v22.23.4-win-x64/node.exe", data)
            output.writestr("../unexpected.txt", b"unwanted")
        target = self.base / "node runtime/node.exe"
        with patch.object(tooling, "NODE_EXE_SHA256", hashlib.sha256(data).hexdigest(), create=True):
            tooling.extract_node(archive, target)
        self.assertEqual(target.read_bytes(), data)
        self.assertFalse((self.base.parent / "unexpected.txt").exists())

    def test_node_extraction_hash_failure_preserves_installed_executable(self):
        archive = self.base / "node.zip"
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("node-v22.23.4-win-x64/node.exe", b"corrupt executable")
        target = self.base / "node.exe"
        target.write_bytes(b"working node")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            tooling.extract_node(archive, target)
        self.assertEqual(target.read_bytes(), b"working node")

    def make_check_layout(self, missing=()):
        layout = tooling.Layout(self.base / "repository", self.base / "dependencies", self.base / "Git")
        files = {"python": layout.python, "bash": layout.bash,
                 "msys": layout.git / "usr/bin/msys-2.0.dll", "flock": layout.flock,
                 "xray": layout.xray, "ruby": layout.ruby, "node": layout.node}
        for name, path in files.items():
            if name not in missing:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes((name + " executable").encode())
        if "ruby" not in missing:
            library = layout.ruby.parent.parent / "lib/yaml.rb"
            library.parent.mkdir()
            library.write_bytes(b"YAML fixture")
        requirements = layout.repository / "tests/requirements.txt"
        requirements.parent.mkdir(parents=True)
        requirements.write_text("PyYAML==6.0.3\nlupa==2.8\n", encoding="utf-8")
        for name in ("flock", "xray", "ruby", "node"):
            self.enterContext(patch.object(tooling, name.upper() + "_EXE_SHA256",
                                          hashlib.sha256((name + " executable").encode()).hexdigest(), create=True))
        self.enterContext(patch.object(tooling, "RUBY_RUNTIME_SHA256", RUBY_FIXTURE_SHA256, create=True))
        return layout

    def probe_output(self, layout, ruby="3.4.9", node="22.23.4"):
        def probe(command, environment, cwd):
            self.assertEqual(environment["RUBY"], str(layout.ruby))
            self.assertEqual(environment["NODE"], str(layout.node))
            executable = Path(command[0])
            if executable == layout.python:
                return '{"PyYAML":"6.0.3","lupa":"2.8"}'
            if executable == layout.bash:
                return str(layout.python) if command[4].startswith("python ") else "flock from util-linux 2.40.2"
            if executable == layout.xray:
                return "Xray 26.7.11 fixture"
            if executable == layout.ruby:
                return ruby
            if executable == layout.node:
                return node
            self.fail("unexpected dependency selected: " + str(executable))
        return probe

    def test_check_rejects_missing_managed_ruby_or_node_without_downloading(self):
        for missing in ("ruby", "node"):
            with self.subTest(dependency=missing):
                # Each fixture has otherwise valid pinned dependencies. Inherited
                # global tools must never satisfy a missing managed installation.
                with tempfile.TemporaryDirectory(dir=self.base) as directory:
                    original = self.base
                    self.base = Path(directory)
                    try:
                        layout = self.make_check_layout(missing=(missing,))
                        with patch.object(tooling, "checked_output", side_effect=self.probe_output(layout)):
                            with patch.object(tooling.urllib.request, "urlopen", side_effect=AssertionError("offline check downloaded")):
                                with self.assertRaisesRegex(ValueError, "missing dependency.*" + missing):
                                    tooling.check(layout)
                    finally:
                        self.base = original

    def test_check_reports_verified_ruby_and_node_versions_and_pins(self):
        layout = self.make_check_layout()
        with patch.object(tooling, "checked_output", side_effect=self.probe_output(layout)):
            report = tooling.check(layout)
        self.assertEqual(report.get("ruby_version"), "3.4.9")
        self.assertEqual(report.get("node_version"), "22.23.4")
        self.assertEqual(report.get("ruby_runtime_sha256"), RUBY_FIXTURE_SHA256)
        self.assertEqual(report.get("ruby_executable_sha256"), hashlib.sha256(b"ruby executable").hexdigest())
        self.assertEqual(report.get("node_executable_sha256"), hashlib.sha256(b"node executable").hexdigest())

    def test_check_rejects_wrong_runtime_versions(self):
        layout = self.make_check_layout()
        for ruby, node, expected in [("3.3.9", "22.23.4", "Ruby"), ("3.4.9", "22.0.0", "Node")]:
            with self.subTest(dependency=expected):
                with patch.object(tooling, "checked_output", side_effect=self.probe_output(layout, ruby, node)):
                    with self.assertRaisesRegex(ValueError, "unexpected " + expected + " version"):
                        tooling.check(layout)

    def test_check_rejects_changed_ruby_library(self):
        layout = self.make_check_layout()
        (layout.ruby.parent.parent / "lib/yaml.rb").write_bytes(b"injected library")
        with patch.object(tooling, "checked_output", side_effect=self.probe_output(layout)):
            with self.assertRaisesRegex(ValueError, "Ruby runtime SHA-256"):
                tooling.check(layout)

    def test_install_fetches_verified_runtimes_and_repairs_from_cache_offline(self):
        layout = self.make_check_layout(missing=("ruby", "node"))
        original_flock_inode = layout.flock.stat().st_ino
        ruby_data = self.make_ruby_archive().read_bytes()
        node_archive = self.base / "node.zip"
        with zipfile.ZipFile(node_archive, "w") as output:
            output.writestr("node-v22.23.4-win-x64/node.exe", b"node executable")
        node_data = node_archive.read_bytes()
        self.enterContext(patch.object(tooling, "RUBY_ARCHIVE_SHA256", hashlib.sha256(ruby_data).hexdigest(), create=True))
        self.enterContext(patch.object(tooling, "NODE_ARCHIVE_SHA256", hashlib.sha256(node_data).hexdigest(), create=True))
        # install() itself is Windows-only, while this offline contract also
        # runs in Linux CI. Map its native tar boundary to the host's real tar.
        system_root = self.base / "Windows"
        native_tar = system_root / "System32/tar.exe"
        native_tar.parent.mkdir(parents=True)
        native_tar.write_bytes(b"native tar boundary")
        self.enterContext(patch.dict(os.environ, {"SystemRoot": str(system_root)}))
        native_run = tooling.subprocess.run

        def run_without_pip_download(command, *args, **kwargs):
            if command[:3] == [str(layout.python), "-m", "pip"]:
                return subprocess.CompletedProcess(command, 0)
            if command[0] == str(native_tar):
                command = [TAR, *command[1:]]
            return native_run(command, *args, **kwargs)

        def release_download(request, **kwargs):
            urls = {
                "https://github.com/oneclick/rubyinstaller2/releases/download/RubyInstaller-3.4.9-1/rubyinstaller-3.4.9-1-x64.7z": ruby_data,
                "https://nodejs.org/download/release/v22.23.4/node-v22.23.4-win-x64.zip": node_data,
            }
            return io.BytesIO(urls[request.full_url])

        with patch.object(tooling.subprocess, "run", side_effect=run_without_pip_download):
            with patch.object(tooling, "checked_output", side_effect=self.probe_output(layout)):
                with patch.object(tooling.urllib.request, "urlopen", side_effect=release_download):
                    report = tooling.install(layout)
                self.assertEqual(report.get("ruby_version"), "3.4.9")
                self.assertEqual(report.get("node_version"), "22.23.4")
                self.assertEqual(layout.ruby.read_bytes(), b"ruby executable")
                self.assertEqual(layout.node.read_bytes(), b"node executable")
                self.assertNotEqual(layout.flock.stat().st_ino, original_flock_inode)
                self.assertEqual(layout.flock.read_bytes(), b"flock executable")
                self.assertTrue((layout.dependencies / "environment.json").is_file())
                (layout.ruby.parent.parent / "lib/yaml.rb").write_bytes(b"damaged library")
                layout.node.write_bytes(b"damaged executable")
                with patch.object(tooling.urllib.request, "urlopen", side_effect=AssertionError("cache repair downloaded")):
                    repaired = tooling.install(layout)
                self.assertEqual(repaired["ruby_runtime_sha256"], RUBY_FIXTURE_SHA256)
                self.assertEqual(layout.node.read_bytes(), b"node executable")

    def test_child_environment_is_isolated_and_uses_selected_dependencies(self):
        layout = tooling.Layout(self.base / "repository", self.base / "dependencies", self.base / "Git")
        inherited = {"PATH": "existing", "PYTHONPATH": "injected", "PYTHONHOME": "other python", "KEEP": "yes",
                     "RUBY": "old-ruby", "NODE": "old-node", "OPENCLASH_REQUIRE_RUBY34": "0", "PYTHONUTF8": "0",
                     "RUBYOPT": "-rinjected", "RUBYLIB": "injected", "GEM_HOME": "injected",
                     "GEM_PATH": "injected", "NODE_OPTIONS": "--require=injected", "NODE_PATH": "injected"}
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
        self.assertEqual(environment["PYTHONUTF8"], "1")
        self.assertEqual(environment["RUBY"], str(layout.dependencies / "rubyinstaller-3.4.9-1-x64/bin/ruby.exe"))
        self.assertEqual(environment["NODE"], str(layout.dependencies / "node-22.23.4/node.exe"))
        self.assertEqual(environment["OPENCLASH_REQUIRE_RUBY34"], "1")
        self.assertEqual(environment.get("OPENCLASH_REQUIRE_NODE"), "1")
        self.assertEqual(environment.get("REQUIRE_XRAY_TEST_CORE"), "1")
        for name in ("RUBYOPT", "RUBYLIB", "GEM_HOME", "GEM_PATH", "NODE_OPTIONS", "NODE_PATH"):
            self.assertNotIn(name, environment)

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
