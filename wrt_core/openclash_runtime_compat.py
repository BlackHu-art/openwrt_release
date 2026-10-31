#!/usr/bin/env python3
"""Prepare the reviewed stable OpenClash patch stack without accepting source drift."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile


PATCHES = (
    "openclash-wan-subnets.patch",
    "openclash-checksum-filename.patch",
    "openclash-ruby-ast.patch",
    "openclash-dashboard-switch.patch",
    "openclash-filename-safety.patch",
    "openclash-tun-stack.patch",
    "openclash-subscription-safety.patch",
    "openclash-group-rename.patch",
    "openclash-etag-lock.patch",
)


def git(directory, *arguments, check=True):
    result = subprocess.run(["git", "-C", str(directory), *map(str, arguments)],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and result.returncode:
        raise ValueError("OpenClash patch preflight failed: " + result.stdout + result.stderr)
    return result


def blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def prepare(core, package):
    core, package = Path(core).resolve(), Path(package).resolve()
    protected = (core / "managed", core.parent / "maintenance")
    if any(package.is_relative_to(directory) for directory in protected):
        raise ValueError("OpenClash original source directories are protected; prepare a build copy")
    receipt = json.loads((core / "compat/openclash-runtime/sources.json").read_text(encoding="utf-8"))
    files = receipt["files"]
    patches = [core / "patches" / name for name in PATCHES]
    if not package.is_dir() or not files or any(not path.is_file() for path in patches):
        raise ValueError("OpenClash source package or reviewed patch is missing")
    originals = {}
    for name in files:
        relative = PurePosixPath(name)
        path = package / name
        if (relative.is_absolute() or ".." in relative.parts or "\\" in name
                or path.is_symlink() or not path.resolve().is_relative_to(package) or not path.is_file()):
            raise ValueError("OpenClash source file is missing or unsafe: " + name)
        originals[name] = path.read_bytes()

    # Undo only complete known patches in an isolated repository. Every resulting
    # file must match the reviewed baseline; partial patches and unknown upstream
    # edits fail before the first write to the build copy.
    with tempfile.TemporaryDirectory(prefix="openclash-compat-") as directory:
        scratch = Path(directory)
        git(scratch, "init", "-q")
        git(scratch, "config", "core.autocrlf", "false")
        for name, data in originals.items():
            target = scratch / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        for patch in reversed(patches):
            if git(scratch, "apply", "--reverse", "--check", patch, check=False).returncode == 0:
                git(scratch, "apply", "--reverse", patch)
        for name, expected in files.items():
            if blob((scratch / name).read_bytes()) != expected:
                raise ValueError("OpenClash source drift or incomplete patch: " + name)
        for patch in patches:
            git(scratch, "apply", patch)
        replacements = {name: (scratch / name).read_bytes() for name in files
                        if originals[name] != (scratch / name).read_bytes()}

    # Stage every replacement first, preserving each build-copy file's mode.
    # Preflight failures never modify sources; failed publication restores files
    # that had already been replaced before propagating the IO error.
    staged, backups, published = {}, {}, []
    try:
        for name, data in replacements.items():
            target = package / name
            fd, temporary = tempfile.mkstemp(prefix=target.name + ".compat-", dir=target.parent)
            staged[name] = Path(temporary)
            with os.fdopen(fd, "wb") as output:
                output.write(data)
            # Content changes must advance mtime: OpenWrt's default prepare
            # stamp fingerprints paths and timestamps. Keep only permissions
            # here; the rollback backup below retains the original metadata.
            shutil.copymode(target, temporary)
            fd, backup = tempfile.mkstemp(prefix=target.name + ".rollback-", dir=target.parent)
            backups[name] = Path(backup)
            with os.fdopen(fd, "wb") as output:
                output.write(originals[name])
            shutil.copystat(target, backup)
        for name, temporary in staged.items():
            os.replace(temporary, package / name)
            published.append(name)
    except OSError:
        for name in reversed(published):
            os.replace(backups.pop(name), package / name)
        raise
    finally:
        for temporary in (*staged.values(), *backups.values()):
            temporary.unlink(missing_ok=True)
    return len(replacements)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare"])
    parser.add_argument("--core", type=Path, required=True)
    parser.add_argument("--package", type=Path, required=True)
    args = parser.parse_args()
    try:
        changed = prepare(args.core, args.package)
    except (OSError, ValueError, KeyError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print("OpenClash reviewed compatibility stack ready; changed files: " + str(changed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
