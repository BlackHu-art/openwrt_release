#!/usr/bin/env python3
"""Validate and materialize repository-owned OpenWrt package sources, offline."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import tempfile

DEFAULT_SOURCES = Path(__file__).resolve().parent / "managed"
MODES = {"100644": 0o644, "100755": 0o755, "120000": None}


def relative_path(value):
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value or ":" in value:
        raise ValueError(f"unsafe manifest path: {value!r}")
    if path.as_posix() != value or value == ".":
        raise ValueError(f"noncanonical manifest path: {value!r}")
    return Path(*path.parts)


def read_lock(sources):
    lock = json.loads((Path(sources) / "sources.lock.json").read_text(encoding="utf-8"))
    if lock.get("schema_version") != 1 or not isinstance(lock.get("packages"), dict):
        raise ValueError("unsupported managed package lock")
    return lock


def verify_package(sources, package_id, lock=None):
    sources = Path(sources).resolve()
    lock = read_lock(sources) if lock is None else lock
    if package_id not in lock["packages"]:
        raise ValueError(f"unknown managed package: {package_id}")
    entry = lock["packages"][package_id]
    package = sources / relative_path(entry["path"])
    if package.is_symlink() or not package.resolve().is_relative_to(sources):
        raise ValueError(f"managed package escapes source root: {package_id}")
    expected = {}
    for item in entry["files"]:
        name = item["path"]
        relative_path(name)
        if name in expected or item["mode"] not in MODES:
            raise ValueError(f"invalid managed file entry: {package_id}/{name}")
        expected[name] = item
    actual = {p.relative_to(package).as_posix(): p for p in package.rglob("*")
              if p.is_file() or p.is_symlink()}
    if not expected or set(expected) != set(actual):
        raise ValueError(f"managed file set mismatch for {package_id}: "
                         f"missing={sorted(set(expected) - set(actual))}, "
                         f"extra={sorted(set(actual) - set(expected))}")
    for name, item in expected.items():
        path = actual[name]
        if path.is_symlink() or not path.resolve().is_relative_to(package.resolve()):
            raise ValueError(f"source must contain recorded link text, not a filesystem link: {path}")
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != item["sha256"]:
            raise ValueError(f"managed file hash mismatch: {package_id}/{name}")
        if item["mode"] == "120000":
            target = content.decode("utf-8")
            link = PurePosixPath(target)
            # Only package-local relative links are used by these sources.
            if link.is_absolute() or "\\" in target or ":" in target or "\x00" in target:
                raise ValueError(f"unsafe package symlink: {package_id}/{name}")
            resolved = (path.parent / target).resolve()
            if not resolved.is_relative_to(package.resolve()):
                raise ValueError(f"package symlink escapes package: {package_id}/{name}")
    return package, expected


def stage_package(sources, package_id, destination, build_root):
    package, files = verify_package(sources, package_id)
    destination = Path(destination)
    build_root = Path(build_root).resolve()
    resolved = destination.resolve()
    if resolved == build_root or not resolved.is_relative_to(build_root):
        raise ValueError(f"destination must be below build root: {destination}")
    if resolved == Path(sources).resolve() or resolved.is_relative_to(Path(sources).resolve()):
        raise ValueError("cannot stage onto managed sources")
    if destination.is_symlink():
        raise ValueError(f"package destination itself must not be a symlink: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix=f".{destination.name}.managed-", dir=destination.parent))
    try:
        for name, item in files.items():
            target = scratch / relative_path(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            if item["mode"] == "120000":
                os.symlink((package / name).read_text(encoding="utf-8"), target)
            else:
                shutil.copyfile(package / name, target)
                target.chmod(MODES[item["mode"]])
        # Build trees are disposable source trees. Runtime /etc and overlays are
        # never passed here. Validate/copy everything before replacing old input.
        if destination.exists():
            shutil.rmtree(destination)
        scratch.rename(destination)
    finally:
        if scratch.exists():
            shutil.rmtree(scratch)


def stage_support(sources, name, destination, build_root):
    lock = read_lock(sources)
    entries = {item["path"]: item for item in lock.get("supplemental_files", [])}
    if name not in entries or not name.startswith("compat/"):
        raise ValueError(f"unknown managed support file: {name}")
    source = Path(sources) / relative_path(name)
    content = source.read_bytes()
    if source.is_symlink() or hashlib.sha256(content).hexdigest() != entries[name]["sha256"]:
        raise ValueError(f"managed support hash mismatch: {name}")
    destination = Path(destination)
    resolved, build = destination.resolve(), Path(build_root).resolve()
    if destination.is_symlink() or resolved == build or not resolved.is_relative_to(build):
        raise ValueError("managed support destination must be below build root")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)


def verify_all(sources):
    lock = read_lock(sources)
    for package_id in lock["packages"]:
        verify_package(sources, package_id, lock)
    for item in lock.get("supplemental_files", []):
        path = Path(sources) / relative_path(item["path"])
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError(f"supplemental source hash mismatch: {item['path']}")
    return len(lock["packages"])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check")
    stage = commands.add_parser("stage")
    stage.add_argument("package")
    stage.add_argument("destination", type=Path)
    stage.add_argument("--build-root", required=True, type=Path)
    support = commands.add_parser("support")
    support.add_argument("name")
    support.add_argument("destination", type=Path)
    support.add_argument("--build-root", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            print(f"Managed package sources: {verify_all(args.sources)} packages verified")
        elif args.command == "support":
            stage_support(args.sources, args.name, args.destination, args.build_root)
        else:
            stage_package(args.sources, args.package, args.destination, args.build_root)
            print(f"Managed source staged: {args.package}")
    except (ValueError, OSError, KeyError) as error:
        print(f"Managed source error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
