#!/usr/bin/env python3
"""Install, check, or run the pinned Windows regression environment."""
import argparse
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import signal
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request

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
XRAY_EXE_SHA256 = "4b43c5ef596f326b233717b585d31a85dd5cd5f77d8da872e75f7ebc00e99acb"
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
    def bash(self):
        return self.git / "bin/bash.exe"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def matches_hash(path, expected):
    return Path(path).is_file() and sha256(path) == expected


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="verified-", dir=path.parent) as directory:
        staged = Path(directory) / "content"
        staged.write_bytes(data)
        os.replace(staged, path)


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


def validate_dependency_location(repository, dependencies):
    repository, dependencies = Path(repository).resolve(), Path(dependencies).resolve()
    if dependencies == repository or repository in dependencies.parents:
        raise ValueError("keep --deps-dir outside the repository (binaries and logs are local only)")


def child_environment(layout, inherited=None):
    environment = dict(os.environ if inherited is None else inherited)
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    paths = [layout.python.parent, layout.flock.parent, layout.git / "bin", layout.git / "usr/bin"]
    environment["PATH"] = os.pathsep.join([str(path) for path in paths] + [environment.get("PATH", "")])
    environment["SSRP_TEST_FLOCK_DIR"] = str(layout.flock.parent)
    environment["XRAY_TEST_BINARY"] = str(layout.xray)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
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
    require_files([layout.python, layout.bash, layout.git / "usr/bin/msys-2.0.dll", layout.flock, layout.xray])
    for path, digest in [(layout.flock, FLOCK_EXE_SHA256), (layout.xray, XRAY_EXE_SHA256)]:
        if not matches_hash(path, digest):
            raise ValueError("SHA-256 mismatch: " + str(path) + "; rerun install to restore the pinned version")
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
    return {"python": str(layout.python), "python_packages": actual,
            "requirements_sha256": sha256(layout.repository / "tests/requirements.txt"),
            "flock": str(layout.flock), "flock_version": flock_version,
            "flock_url": FLOCK_URL, "flock_archive_sha256": FLOCK_ARCHIVE_SHA256,
            "flock_executable_sha256": sha256(layout.flock),
            "xray": str(layout.xray), "xray_version": core_version,
            "xray_archive_sha256": ASSETS["windows-amd64"][2], "xray_executable_sha256": sha256(layout.xray),
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
    if not matches_hash(layout.xray, XRAY_EXE_SHA256):
        with tempfile.TemporaryDirectory(prefix="xray-install-", dir=layout.dependencies) as directory:
            executable, _ = fetch_core(Path(directory) / "xray.exe", "windows-amd64")
            if not matches_hash(executable, XRAY_EXE_SHA256):
                raise ValueError("Xray executable SHA-256 mismatch")
            atomic_write(layout.xray, executable.read_bytes())
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
        print("Environment verified:", report["flock_version"], "; Xray", XRAY_VERSION, flush=True)
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
