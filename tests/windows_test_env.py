#!/usr/bin/env python3
"""Install, check, or run the pinned Windows regression environment."""
import argparse
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import signal
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile

# Keep imports from creating untracked bytecode in a clean checkout.
sys.dont_write_bytecode = True
from fetch_xray_test_core import ASSETS, VERSION as XRAY_VERSION, fetch_core


ROOT = Path(__file__).resolve().parents[1]
# Existing regression fixtures also use this Git for Windows installation.
GIT_ROOT = Path("C:/Program Files/Git")
FLOCK_VERSION = "2.40.2-2"
FLOCK_PACKAGE = "util-linux-" + FLOCK_VERSION + "-x86_64.pkg.tar.zst"
FLOCK_URL = "https://repo.msys2.org/msys/x86_64/" + FLOCK_PACKAGE
FLOCK_ARCHIVE_SHA256 = "969edb185d37986e6feddb3c54807598e3cc6774b736fec3a27d5d27731f7fdd"
FLOCK_EXE_SHA256 = "20ea2583f3c464a19dcb618141866c4f5794842952259edcc578feec79917b8a"
XRAY_EXE_SHA256 = "c77a00eb84fb93ae044c2d771a1cabcc033b81e487253fbc35b12df6879c1e15"
RUBY_VERSION = "3.4.9"
RUBY_RELEASE = "3.4.9-1"
RUBY_DIRECTORY = "rubyinstaller-" + RUBY_RELEASE + "-x64"
RUBY_ARCHIVE = RUBY_DIRECTORY + ".7z"
RUBY_URL = ("https://github.com/oneclick/rubyinstaller2/releases/download/RubyInstaller-"
            + RUBY_RELEASE + "/" + RUBY_ARCHIVE)
RUBY_ARCHIVE_SHA256 = "4375268618b61dadf53bf8e54beaca74ea30580c90d3c47ea9f2a134bd3e494e"
RUBY_EXE_SHA256 = "77e75784ff76f347ae316150b5b7b2f5eb91bb264ab39c6820600d1b3df6b6bb"
# Complete bin+lib tree from the verified portable release, including Psych DLLs.
RUBY_RUNTIME_SHA256 = "0480aa03bcbbd69919f0fccecb0000076081c8186100a6096c302cb304d211ee"
NODE_VERSION = "22.23.4"
NODE_DIRECTORY = "node-v" + NODE_VERSION + "-win-x64"
NODE_ARCHIVE = NODE_DIRECTORY + ".zip"
NODE_URL = "https://nodejs.org/download/release/v" + NODE_VERSION + "/" + NODE_ARCHIVE
# Both hashes are published in the fixed release's official SHASUMS256.txt.
NODE_ARCHIVE_SHA256 = "cbc74b5e0982c9dbb41525fd8fb5dcd32fbee237863f7829072f4639a1ce5f20"
NODE_EXE_SHA256 = "dccc52de28d8df2ee22d2062424f8c563070d95d8ad70c54c4bf01d590dec14f"
MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class Layout:
    repository: Path
    dependencies: Path
    git: Path = GIT_ROOT

    @property
    def python(self):
        return self.dependencies / "python-venv/Scripts/python.exe"

    @property
    def flock(self):
        return self.dependencies / ("flock-" + FLOCK_VERSION) / "usr/bin/flock.exe"

    @property
    def xray(self):
        return self.dependencies / ("xray-" + XRAY_VERSION) / "xray.exe"

    @property
    def ruby(self):
        return self.dependencies / RUBY_DIRECTORY / "bin/ruby.exe"

    @property
    def node(self):
        return self.dependencies / ("node-" + NODE_VERSION) / "node.exe"

    @property
    def bash(self):
        return self.git / "bin/bash.exe"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def matches_hash(path, expected):
    return Path(path).is_file() and sha256(path) == expected


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # MSYS flock cannot fork after a file first created without an .exe suffix
    # is renamed to .exe. Preserve the suffix and the destination parent's ACL.
    descriptor, staged = tempfile.mkstemp(prefix="verified-", suffix=path.suffix, dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(data)
        os.replace(staged, path)
    finally:
        Path(staged).unlink(missing_ok=True)


def write_json(path, value):
    atomic_write(path, (json.dumps(value, ensure_ascii=True, indent=2) + "\n").encode("utf-8"))


def download_verified(url, output, expected):
    started = time.monotonic()
    data = bytearray()
    request = urllib.request.Request(url, headers={"User-Agent": "openwrt-release-windows-tests"})
    with urllib.request.urlopen(request, timeout=30) as response:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > MAX_DOWNLOAD_BYTES or time.monotonic() - started > 120:
                raise ValueError("download exceeds the bounded budget")
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("download SHA-256 mismatch: " + url)
    atomic_write(output, data)


def extract_flock(archive, tar, output):
    # Read one exact member to stdout; never extract archive paths to disk.
    result = subprocess.run([str(tar), "-xOf", str(archive), "usr/bin/flock.exe"],
                            capture_output=True, check=True, timeout=60)
    if hashlib.sha256(result.stdout).hexdigest() != FLOCK_EXE_SHA256:
        raise ValueError("flock executable SHA-256 mismatch")
    atomic_write(output, result.stdout)


def tree_sha256(directory):
    directory = Path(directory)
    digest = hashlib.sha256()
    for path in sorted(directory.rglob("*"), key=lambda item: item.relative_to(directory).as_posix()):
        if path.is_symlink():
            raise ValueError("Ruby runtime must not contain symbolic links: " + str(path))
        if path.is_file():
            digest.update(path.relative_to(directory).as_posix().encode("utf-8") + b"\0")
            digest.update(bytes.fromhex(sha256(path)))
    return digest.hexdigest()


def extract_ruby(archive, tar, output):
    # Validate archive names before native extraction, then retain only the
    # runtime directories. Headers, gems for build tools, and docs are not needed.
    members = subprocess.run([str(tar), "-tf", str(archive)], capture_output=True, check=True,
                             text=True, encoding="utf-8", errors="strict", timeout=60)
    for name in members.stdout.splitlines():
        path = PurePosixPath(name.replace("\\", "/"))
        if (path.is_absolute() or not path.parts or path.parts[0] != RUBY_DIRECTORY
                or ".." in path.parts or any(":" in part for part in path.parts)):
            raise ValueError("unsafe Ruby archive path: " + name)
    output = Path(output)
    if output.is_symlink():
        raise ValueError("Ruby runtime directory must not be a symbolic link")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ruby-install-", dir=output.parent) as directory:
        staged = Path(directory)
        subprocess.run([str(tar), "-xf", str(archive), "-C", str(staged), "--",
                        RUBY_DIRECTORY + "/bin", RUBY_DIRECTORY + "/lib"],
                       capture_output=True, check=True, timeout=120)
        runtime = staged / RUBY_DIRECTORY
        if tree_sha256(runtime) != RUBY_RUNTIME_SHA256:
            raise ValueError("Ruby runtime SHA-256 mismatch")
        # Swap only this managed directory after the entire staged tree passes.
        # Keep the old directory available for rollback until replacement succeeds.
        previous = staged / "previous"
        if output.exists():
            output.rename(previous)
        try:
            runtime.rename(output)
        except OSError:
            if previous.exists():
                previous.rename(output)
            raise


def extract_node(archive, output):
    # Node's built-in modules need only node.exe. Never extract ZIP paths to disk.
    try:
        with zipfile.ZipFile(archive) as source:
            member = source.getinfo(NODE_DIRECTORY + "/node.exe")
            if member.file_size > 128 * 1024 * 1024:
                raise ValueError("Node executable exceeds the bounded budget")
            data = source.read(member)
    except (KeyError, zipfile.BadZipFile) as error:
        raise ValueError("invalid Node archive: " + str(error)) from error
    if hashlib.sha256(data).hexdigest() != NODE_EXE_SHA256:
        raise ValueError("Node executable SHA-256 mismatch")
    atomic_write(output, data)


def validate_dependency_location(repository, dependencies):
    repository, dependencies = Path(repository).resolve(), Path(dependencies).resolve()
    if dependencies == repository or repository in dependencies.parents:
        raise ValueError("keep --deps-dir outside the repository (binaries and logs are local only)")


def child_environment(layout, inherited=None):
    environment = dict(os.environ if inherited is None else inherited)
    for name in ("PYTHONPATH", "PYTHONHOME", "RUBYOPT", "RUBYLIB", "GEM_HOME", "GEM_PATH",
                 "NODE_OPTIONS", "NODE_PATH"):
        environment.pop(name, None)
    paths = [layout.python.parent, layout.flock.parent, layout.git / "bin", layout.git / "usr/bin"]
    environment["PATH"] = os.pathsep.join([str(path) for path in paths] + [environment.get("PATH", "")])
    environment["SSRP_TEST_FLOCK_DIR"] = str(layout.flock.parent)
    environment["XRAY_TEST_BINARY"] = str(layout.xray)
    environment["REQUIRE_XRAY_TEST_CORE"] = "1"
    environment["RUBY"] = str(layout.ruby)
    environment["NODE"] = str(layout.node)
    environment["OPENCLASH_REQUIRE_RUBY34"] = "1"
    environment["OPENCLASH_REQUIRE_NODE"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONUTF8"] = "1"
    environment["BASH"] = str(layout.bash)
    return environment


def require_files(paths):
    for path in paths:
        if not path.is_file():
            raise ValueError("missing dependency: " + str(path) + "; see docs/windows-testing.md")


def checked_output(command, environment, cwd):
    result = subprocess.run([str(item) for item in command], env=environment, cwd=cwd,
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    if result.returncode:
        raise ValueError("dependency check failed: " + str(command[0]) + "\n" + result.stdout + result.stderr)
    return result.stdout.strip()


def check(layout):
    require_files([layout.python, layout.bash, layout.git / "usr/bin/msys-2.0.dll", layout.flock, layout.xray,
                   layout.ruby, layout.node])
    for path, digest in [(layout.flock, FLOCK_EXE_SHA256), (layout.xray, XRAY_EXE_SHA256),
                         (layout.ruby, RUBY_EXE_SHA256), (layout.node, NODE_EXE_SHA256)]:
        if not matches_hash(path, digest):
            raise ValueError("SHA-256 mismatch: " + str(path) + "; rerun install to restore the pinned version")
    ruby_digest = tree_sha256(layout.ruby.parent.parent)
    if ruby_digest != RUBY_RUNTIME_SHA256:
        raise ValueError("Ruby runtime SHA-256 mismatch; rerun install to restore the pinned version")
    environment = child_environment(layout)
    requirements = (layout.repository / "tests/requirements.txt").read_text(encoding="utf-8")
    expected = dict(line.split("==") for line in requirements.splitlines() if line and not line.startswith("#"))
    probe = (
        "import sys,json,importlib.metadata; from lupa.lua51 import LuaRuntime; import yaml; "
        "assert sys.version_info >= (3,11); assert LuaRuntime().eval('_VERSION') == 'Lua 5.1'; "
        "print(json.dumps({name:importlib.metadata.version(name) for name in sys.argv[1:]}))"
    )
    actual = json.loads(checked_output([layout.python, "-c", probe, *expected], environment, layout.repository))
    if actual != expected:
        raise ValueError("Python dependency versions differ from tests/requirements.txt; rerun install")
    # Verify Bash resolves the selected venv Python, not a user/global interpreter.
    interpreter = checked_output([layout.bash, "--noprofile", "--norc", "-c",
                                  "python -c 'import sys; print(sys.executable)'"], environment, layout.repository)
    if Path(interpreter).resolve() != layout.python.resolve():
        raise ValueError("Git Bash did not select the test venv: " + interpreter)
    with tempfile.TemporaryDirectory(prefix="flock-probe-", dir=layout.dependencies) as directory:
        # Two independent opens must contend; closing the owner must release the lock.
        script = r'''set -eu
lock=$(cygpath -u "$1")
exec 9>"$lock"
flock -n 9
status=0
(exec 9>&-; flock -n "$lock" true) || status=$?
[ "$status" = 1 ] || { echo "flock exclusion failed: $status" >&2; exit 1; }
exec 9>&-
flock -n "$lock" true
flock --version
'''
        flock_version = checked_output([layout.bash, "--noprofile", "--norc", "-c", script,
                                        "probe", str(Path(directory) / "lock")], environment, layout.repository)
    core_version = checked_output([layout.xray, "version"], environment, layout.repository)
    if not core_version.startswith("Xray " + XRAY_VERSION + " "):
        raise ValueError("unexpected Xray version: " + core_version)
    ruby_probe = "require 'yaml'; abort 'YAML check failed' unless YAML.safe_load('value: 7') == {'value'=>7}; puts RUBY_VERSION"
    ruby_version = checked_output([layout.ruby, "-EUTF-8", "-e", ruby_probe], environment, layout.repository)
    if ruby_version != RUBY_VERSION:
        raise ValueError("unexpected Ruby version: " + ruby_version)
    node_probe = ("const assert = require('node:assert/strict'); require('node:fs'); "
                  "assert.equal(require('node:vm').runInNewContext('6 * 7'), 42); "
                  "process.stdout.write(process.versions.node)")
    node_version = checked_output([layout.node, "-e", node_probe], environment, layout.repository)
    if node_version != NODE_VERSION:
        raise ValueError("unexpected Node version: " + node_version)
    return {"python": str(layout.python), "python_packages": actual,
            "requirements_sha256": sha256(layout.repository / "tests/requirements.txt"),
            "flock": str(layout.flock), "flock_version": flock_version,
            "flock_url": FLOCK_URL, "flock_archive_sha256": FLOCK_ARCHIVE_SHA256,
            "flock_executable_sha256": sha256(layout.flock),
            "xray": str(layout.xray), "xray_version": core_version,
            "xray_archive_sha256": ASSETS["windows-amd64"][2], "xray_executable_sha256": sha256(layout.xray),
            "ruby": str(layout.ruby), "ruby_version": ruby_version, "ruby_url": RUBY_URL,
            "ruby_archive_sha256": RUBY_ARCHIVE_SHA256, "ruby_executable_sha256": sha256(layout.ruby),
            "ruby_runtime_sha256": ruby_digest,
            "node": str(layout.node), "node_version": node_version, "node_url": NODE_URL,
            "node_archive_sha256": NODE_ARCHIVE_SHA256, "node_executable_sha256": sha256(layout.node),
            "git_msys_runtime_sha256": sha256(layout.git / "usr/bin/msys-2.0.dll")}


def install(layout):
    tar = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/tar.exe"
    require_files([layout.bash, layout.git / "usr/bin/msys-2.0.dll", tar])
    layout.dependencies.mkdir(parents=True, exist_ok=True)
    environment = child_environment(layout)
    if not layout.python.exists():
        subprocess.run([sys.executable, "-m", "venv", str(layout.python.parent.parent)], env=environment, check=True)
    subprocess.run([str(layout.python), "-m", "pip", "install", "-r",
                    str(layout.repository / "tests/requirements.txt")], env=environment, check=True)
    if not matches_hash(layout.flock, FLOCK_EXE_SHA256):
        archive = layout.dependencies / ("flock-" + FLOCK_VERSION) / FLOCK_PACKAGE
        if not matches_hash(archive, FLOCK_ARCHIVE_SHA256):
            download_verified(FLOCK_URL, archive, FLOCK_ARCHIVE_SHA256)
        extract_flock(archive, tar, layout.flock)
    else:
        # Repair old installations with correct bytes but non-executable MSYS
        # fork metadata left by the former suffixless temporary-file staging.
        atomic_write(layout.flock, layout.flock.read_bytes())
    if not matches_hash(layout.xray, XRAY_EXE_SHA256):
        with tempfile.TemporaryDirectory(prefix="xray-install-", dir=layout.dependencies) as directory:
            executable, _ = fetch_core(Path(directory) / "xray.exe", "windows-amd64")
            if not matches_hash(executable, XRAY_EXE_SHA256):
                raise ValueError("Xray executable SHA-256 mismatch")
            atomic_write(layout.xray, executable.read_bytes())
    if (not matches_hash(layout.ruby, RUBY_EXE_SHA256)
            or tree_sha256(layout.ruby.parent.parent) != RUBY_RUNTIME_SHA256):
        archive = layout.dependencies / "downloads" / RUBY_ARCHIVE
        if not matches_hash(archive, RUBY_ARCHIVE_SHA256):
            download_verified(RUBY_URL, archive, RUBY_ARCHIVE_SHA256)
        extract_ruby(archive, tar, layout.ruby.parent.parent)
    if not matches_hash(layout.node, NODE_EXE_SHA256):
        archive = layout.dependencies / "downloads" / NODE_ARCHIVE
        if not matches_hash(archive, NODE_ARCHIVE_SHA256):
            download_verified(NODE_URL, archive, NODE_ARCHIVE_SHA256)
        extract_node(archive, layout.node)
    report = check(layout)
    write_json(layout.dependencies / "environment.json", report)
    return report


def timestamp():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def stop_process_tree(child):
    if os.name == "nt":
        # The separate process group prevents console Ctrl+C from killing the
        # root before taskkill can discover its descendants. Never target an
        # already exited PID, which can no longer identify a live process tree.
        if child.poll() is not None:
            raise OSError("regression root already exited; descendant cleanup cannot be confirmed")
        taskkill = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/taskkill.exe"
        subprocess.run([str(taskkill), "/PID", str(child.pid), "/T", "/F"],
                       capture_output=True, check=True, timeout=10,
                       creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        # Descendants retain this group even if its original leader has exited.
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    child.wait(timeout=5)


def run_logged(command, cwd, environment, run_dir, metadata):
    run_dir.mkdir(parents=True, exist_ok=False)
    result = dict(metadata, command=[str(item) for item in command], repository=str(cwd), started_at=timestamp())
    exit_code = 1
    process_group = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
                     else {"start_new_session": True})
    with (run_dir / "regression.log").open("w", encoding="utf-8") as log:
        try:
            with subprocess.Popen(command, cwd=cwd, env=environment, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                                  **process_group) as child:
                try:
                    for line in child.stdout:
                        print(line, end="", flush=True)
                        log.write(line)
                        log.flush()
                    exit_code = child.wait()
                except KeyboardInterrupt:
                    exit_code = 130
                    result["error"] = "interrupted"
                    try:
                        stop_process_tree(child)
                    except (OSError, subprocess.SubprocessError) as error:
                        result["cleanup_error"] = str(error)
                        log.write("Process cleanup failed: " + str(error) + "\n")
                        if child.poll() is None:
                            child.kill()
                        child.wait(timeout=5)
        except OSError as error:
            result["error"] = str(error)
            log.write(str(error) + "\n")
    result.update(exit_code=exit_code, finished_at=timestamp())
    write_json(run_dir / "result.json", result)
    print("Regression exit code:", exit_code, "\nLogs:", run_dir, flush=True)
    return exit_code


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["install", "check", "run"])
    parser.add_argument("--deps-dir", type=Path, help="dependency/log directory outside the checkout")
    args = parser.parse_args(argv)
    try:
        if (os.name != "nt" or platform.machine().lower() not in {"amd64", "x86_64"}
                or struct.calcsize("P") != 8 or sys.version_info < (3, 11)):
            raise ValueError("use Windows x64 Python 3.11+; Linux CI continues to use tests/run_all.sh")
        dependencies = args.deps_dir
        if dependencies is None:
            if not os.environ.get("LOCALAPPDATA"):
                raise ValueError("LOCALAPPDATA is unavailable; supply --deps-dir")
            dependencies = Path(os.environ["LOCALAPPDATA"]) / "openwrt-release-test-deps"
        dependencies = dependencies.expanduser().resolve()
        validate_dependency_location(ROOT, dependencies)
        if args.action == "install":
            dependencies.mkdir(parents=True, exist_ok=True)
            # Store applications can redirect a newly created LocalAppData path.
            dependencies = dependencies.resolve()
            validate_dependency_location(ROOT, dependencies)
        layout = Layout(ROOT, dependencies)
        print("Dependencies:", dependencies, flush=True)
        report = install(layout) if args.action == "install" else check(layout)
        print("Environment verified:", report["flock_version"], "; Xray", XRAY_VERSION,
              "; Ruby", report["ruby_version"], "; Node", report["node_version"], flush=True)
        for name in ("ruby", "node"):
            print(name.capitalize() + " source:", report[name + "_url"],
                  "\nArchive SHA-256:", report[name + "_archive_sha256"],
                  "\nExecutable SHA-256:", report[name + "_executable_sha256"], flush=True)
        print("Ruby runtime SHA-256:", report["ruby_runtime_sha256"], flush=True)
        if args.action == "run":
            run_dir = dependencies / "runs" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            command = [str(layout.bash), "--noprofile", "--norc", "-x", "tests/run_all.sh"]
            print("Regression logs:", run_dir, flush=True)
            return run_logged(command, ROOT, child_environment(layout), run_dir, {"environment": report})
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print("ERROR:", error, file=sys.stderr)
        print("See docs/windows-testing.md; install dependencies before check/run.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
