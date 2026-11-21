#!/usr/bin/env python3
"""Omit automatic Timecontrol migration from the reviewed Netcontrol build copy.

Source: rule2c/luci-app-netcontrol@61364846e1188d87801f778749efc4f2a4deac43.
Only the initializer changes; the upstream source fixture stays byte-identical.
"""
import argparse
import hashlib
import os
from pathlib import Path
import stat
import sys
import tempfile


BASE = Path(__file__).resolve().parent
INITIALIZER = "root/etc/uci-defaults/luci-netcontrol"
RAW_SHA256 = "1b319a664589868b1daa65b5d980a3f5d486b96e4701fe178374ae44306d38cc"
PREPARED_SHA256 = "94a43eb6212194c20f5f0c3af282cc7cfec6f3d330fbd862aa3f09ca3968fc4f"


def prepare(package_dir):
    package = Path(package_dir)
    root = package.resolve()
    forbidden = (BASE / "managed", BASE.parent / "tests/fixtures", BASE.parent / "maintenance")
    if (package.is_symlink() or not package.is_dir() or
            any(root.is_relative_to(path.resolve()) for path in forbidden)):
        raise ValueError("Netcontrol preparation requires a separate build copy")
    target = package
    for part in Path(INITIALIZER).parts:
        target /= part
        if target.is_symlink():
            raise ValueError("Netcontrol initializer path contains a symlink")
    if not target.is_file() or not target.resolve().is_relative_to(root):
        raise ValueError("Netcontrol initializer is missing or outside the build copy")
    original = target.read_bytes()
    digest = hashlib.sha256(original).hexdigest()
    if digest == PREPARED_SHA256:
        return False
    if digest != RAW_SHA256:
        raise ValueError("Netcontrol initializer has unreviewed source drift; no files changed")

    start = original.index("# ── 从旧包 luci-app-timecontrol 迁移".encode())
    end = original.index("# 注册开机自启".encode())
    prepared = (original[:start] +
                b"# This build adds Netcontrol without migrating or modifying Timecontrol.\n\n" +
                original[end:])
    if hashlib.sha256(prepared).hexdigest() != PREPARED_SHA256:
        raise ValueError("Netcontrol derived initializer differs from its reviewed identity")

    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".netcontrol-compat-", dir=target.parent,
                                         delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(prepared)
        temporary.chmod(stat.S_IMODE(target.stat().st_mode))
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package_dir", type=Path)
    arguments = parser.parse_args()
    try:
        changed = prepare(arguments.package_dir)
    except (OSError, ValueError) as error:
        print(f"Netcontrol compatibility error: {error}", file=sys.stderr)
        return 1
    print("Netcontrol independent first-boot setup " + ("prepared" if changed else "verified"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
