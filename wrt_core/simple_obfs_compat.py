#!/usr/bin/env python3
"""Adapt the pinned simple-obfs archive format in disposable build copies only."""
import argparse
import hashlib
import os
from pathlib import Path
import stat
import sys
import tempfile


RAW = Path(__file__).resolve().parent / "managed/packages/simple-obfs"
REVIEWED = {
    "Makefile": "5a33bf0551def77301bfd1b77d190645d8ee1a4bc8f1a73489c9884d9b3cabd9",
    "patches/001-convert-arguments-of-isdigit-to-int.patch":
        "71cedb1b520d7074abe3318ff7042715d5504202f641ca19f17730cc06be21a0",
}
OLD_HASH = b"7a0154d2de18373e52783d1b64cf5204471049c2d2c64f0b3323d7f430aa4275"
# Independently reproduced with the production Git/tar/xz download format from
# simple-obfs 486bebd9208539058e57e23a12f23103016e09b4 and its pinned libcork
# f02984545061c924808e4b9ea7cc6749a41f1979. The source selection is unchanged.
# Explicit -T0 keeps the same multithreaded XZ container with both a fresh
# system xz 5.4.5 and a cached OpenWrt host xz 5.8.3.
ARCHIVE_HASH = b"da5af052265fbfba7a11ee4195257f9bc13f44d054d8fdcbace0639360870035"


def _read_package(directory):
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError(f"simple-obfs package is not a regular directory: {directory}")
    paths = {p.relative_to(directory).as_posix(): p for p in directory.rglob("*")
             if p.is_file() or p.is_symlink()}
    if set(paths) != set(REVIEWED):
        raise ValueError("simple-obfs file set has missing or unreviewed inputs")
    contents = {}
    for relative, path in paths.items():
        if path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()):
            raise ValueError(f"simple-obfs input is not a package-local regular file: {relative}")
        contents[relative] = path.read_bytes()
    return contents


def prepare(package_dir: Path) -> None:
    """Validate the complete original or prepared package before one atomic edit."""
    package_dir = Path(package_dir)
    if package_dir.resolve().is_relative_to(RAW.parent.parent.resolve()):
        raise ValueError("simple-obfs managed originals cannot be modified")
    original = _read_package(RAW)
    for relative, expected in REVIEWED.items():
        if hashlib.sha256(original[relative]).hexdigest() != expected:
            raise ValueError(f"simple-obfs managed source has unreviewed drift: {relative}")
    old_declaration = b"PKG_MIRROR_HASH:=" + OLD_HASH + b"\n"
    if original["Makefile"].count(old_declaration) != 1:
        raise ValueError("simple-obfs reviewed archive hash is not unique")
    prepared_recipe = original["Makefile"].replace(
        old_declaration, b"PKG_MIRROR_HASH:=" + ARCHIVE_HASH + b"\nexport XZ_OPT := -T0\n")
    current = _read_package(package_dir)
    for relative, content in current.items():
        accepted = (original[relative], prepared_recipe) if relative == "Makefile" else (original[relative],)
        if content not in accepted:
            raise ValueError(f"simple-obfs build source has unreviewed drift: {relative}")
        if os.name != "nt" and stat.S_IMODE((package_dir / relative).stat().st_mode) != 0o644:
            raise ValueError(f"simple-obfs build source mode changed: {relative}")
    if current["Makefile"] == prepared_recipe:
        return
    recipe = package_dir / "Makefile"
    descriptor, temporary_name = tempfile.mkstemp(prefix=".simple-obfs-", dir=package_dir)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(prepared_recipe)
        temporary.chmod(stat.S_IMODE(recipe.stat().st_mode))
        os.replace(temporary, recipe)
    finally:
        if temporary.exists():
            temporary.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package_dir", type=Path)
    args = parser.parse_args(argv)
    try:
        prepare(args.package_dir)
    except (OSError, ValueError) as error:
        print(f"simple-obfs compatibility error: {error}", file=sys.stderr)
        return 1
    print("simple-obfs pinned source and archive hash compatibility verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
