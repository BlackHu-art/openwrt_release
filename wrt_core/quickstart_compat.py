#!/usr/bin/env python3
"""Backport reviewed Quickstart runtime fixes into disposable build copies.

Managed originals and their lock remain unchanged. Load the verified offline
status/temperature template into scratch space before applying the local patch.
"""
import argparse
import hashlib
import importlib.util
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile


BASE = Path(__file__).resolve().parent
SOURCES = BASE / "managed"
RAW = SOURCES / "packages/luci-app-quickstart"
PATCH = BASE / "patches/quickstart-runtime-safety.patch"
PATCH_SHA256 = "2dd298a1a3a97b2647923612d21ded2fea7fa00dfc53bd6a857b3c272c5aee13"
REVIEWED = {
    "luasrc/controller/istore_backend.lua": "cec4b600b3f481f22670a1c43c380d2f43793d9d4dbd37c1e3e921083dfff700",
    "luasrc/controller/quickstart.lua": "52bdbd3282d73905ef6ad3d663b9dd66893ebef0586aca649d3e78d277c81075",
    "root/usr/libexec/quickstart/auto_setup.sh": "31f3f9154f055d4ba67b90d5f97f81f9e11267f02d1f1567c1644fb40f1f9f18",
}
BACKEND = "luasrc/controller/istore_backend.lua"
SUPPORT_SHA256 = "5eb5e0524a42b62895ee8163d50bf1d78999db7c1321646fdcca3c99c26249e2"


def _read(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Quickstart input is missing or not a regular file: {path}")
    return path.read_bytes()


def _checked(path, expected):
    data = _read(path)
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError(f"Quickstart reviewed input has unreviewed drift: {path}")
    return data


def _prepared_payloads(original):
    """Use the real managed-support loader, then apply only the reviewed patch."""
    support = _checked(SOURCES / "compat/istore_backend.lua", SUPPORT_SHA256)
    patch = _checked(PATCH, PATCH_SHA256)
    spec = importlib.util.spec_from_file_location("quickstart_managed_support", BASE / "managed_plugins.py")
    loader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loader)
    with tempfile.TemporaryDirectory(prefix="quickstart-patch-") as temporary:
        scratch = Path(temporary)
        for relative, data in original.items():
            path = scratch / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        loader.stage_support(SOURCES, "compat/istore_backend.lua", scratch / BACKEND, scratch)
        # Avoid discovering an unrelated parent Git worktree or inherited Git
        # overrides. Without this boundary git apply can silently skip all hunks.
        environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        environment["GIT_CEILING_DIRECTORIES"] = str(scratch.parent)
        for options in (("--check",), ()):
            result = subprocess.run(["git", "apply", "--whitespace=nowarn", *options, "-"],
                                    input=patch, cwd=scratch, env=environment,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
            if result.returncode:
                raise ValueError("Quickstart derived patch failed: " + result.stderr.decode("utf-8", "replace"))
        prepared = {relative: _read(scratch / relative) for relative in original}
        template_inputs = dict(original, **{BACKEND: support})
        if any(prepared[name] == template_inputs[name] for name in original):
            raise ValueError("Quickstart derived patch did not update every reviewed file")
    return support, prepared


def _publish(package, original, prepared):
    """Stage every file before publication and roll back replacement failures.

    Each replacement is atomic. Rollback covers ordinary I/O errors between
    replacements; interrupted/crashed builds must be restaged by the loader.
    """
    staged, backups, published = {}, {}, []
    try:
        for relative, data in prepared.items():
            destination = package / relative
            mode = stat.S_IMODE(destination.stat().st_mode)
            for collection, content in ((staged, data), (backups, original[relative])):
                with tempfile.NamedTemporaryFile(prefix=".quickstart-", dir=destination.parent,
                                                 delete=False) as stream:
                    path = Path(stream.name)
                    collection[relative] = path
                    stream.write(content)
                path.chmod(mode)
        try:
            for relative, temporary in staged.items():
                os.replace(temporary, package / relative)
                published.append(relative)
        except OSError:
            for relative in reversed(published):
                os.replace(backups[relative], package / relative)
            raise
    finally:
        for path in (*staged.values(), *backups.values()):
            path.unlink(missing_ok=True)


def prepare(package_dir):
    """Accept complete raw/template or complete prepared states, never a mix."""
    package = Path(package_dir)
    resolved = package.resolve()
    repository = BASE.parent
    if (package.is_symlink() or not package.is_dir() or
            resolved.is_relative_to(SOURCES.resolve()) or
            resolved.is_relative_to((repository / "maintenance").resolve())):
        raise ValueError(f"Quickstart preparation requires a separate build copy: {package}")
    original = {name: _checked(RAW / name, expected) for name, expected in REVIEWED.items()}
    actual = {}
    for relative in original:
        path = package / relative
        if not path.resolve().is_relative_to(resolved):
            raise ValueError(f"Quickstart input redirects outside its package: {path}")
        if any(parent.is_symlink() for parent in path.parents if parent != package and package in parent.parents):
            raise ValueError(f"Quickstart nested directory is a symlink: {path}")
        actual[relative] = _read(path)
    support, prepared = _prepared_payloads(original)
    if actual == prepared:
        return {"changed": False}
    template_state = dict(original, **{BACKEND: support})
    if actual not in (original, template_state):
        raise ValueError("Quickstart source drift or partial preparation; no files changed")
    _publish(package, actual, prepared)
    return {"changed": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package_dir", type=Path)
    args = parser.parse_args(argv)
    try:
        result = prepare(args.package_dir)
    except (OSError, ValueError) as error:
        print(f"Quickstart compatibility error: {error}", file=sys.stderr)
        return 1
    print("Quickstart runtime safety " + ("prepared" if result["changed"] else "verified"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
