#!/usr/bin/env python3
"""Adapt the reviewed SmartDNS download recipe in disposable build copies."""
import argparse
import hashlib
import os
from pathlib import Path
import stat
import sys
import tempfile


MAINTENANCE = Path(__file__).resolve().parents[1] / "maintenance"
RAW = MAINTENANCE / "plugins/smartdns/package"
RECIPE_SHA256 = "e0e6589e5031683536bda4665dcbf928cde0fe45c228f74b7ebaab02be342907"
SOURCE_COMMIT = "3261c18b1b93d841e86d9e727557109ae71d71cd"
CORE_COMMIT = "136c0c2690138d6dedd8b520281aafe49112643f"
# Upstream 1db3543c switched to codeload to avoid host-dependent Git repacking.
# Keep our reviewed core commit; independently audited all 445 Git blobs/types/modes.
CORE_ARCHIVE_HASH = "fd7bfb126ba15764d89a3a57efbea67602105a7bf394f81b7b5dd81693ddc5cb"
# Independently reproduced from all 109 Git blobs, normalized GNU tar metadata,
# and gzip -nc. The original hash is correct for the original fixed commit.
ARCHIVE_HASH = "4401734712dd034eb1088ce440d1bc64d053dfcd6f63f66c08cd48ab68593042"


def _read_recipe(directory: Path) -> bytes:
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError(f"SmartDNS package is not a regular directory: {directory}")
    recipe = directory / "Makefile"
    if recipe.is_symlink() or not recipe.is_file():
        raise ValueError(f"SmartDNS Makefile is not a regular file: {recipe}")
    return recipe.read_bytes()


def prepare(package_dir: Path) -> None:
    """Validate the complete original or prepared recipe before one atomic edit."""
    package_dir = Path(package_dir)
    if package_dir.resolve().is_relative_to(MAINTENANCE.resolve()):
        raise ValueError("SmartDNS maintenance originals cannot be modified")
    original = _read_recipe(RAW)
    if hashlib.sha256(original).hexdigest() != RECIPE_SHA256:
        raise ValueError("SmartDNS reviewed source has unreviewed drift: Makefile")
    version = b"\tVERSION:=$(SMARTDNS_WEBUI_SOURCE_VERSION)\n"
    registration = b"$(eval $(call Download,smartdns-webui))\n"
    if original.count(version) != 1 or original.count(registration) != 1:
        raise ValueError("SmartDNS reviewed download declarations are not unique")
    core_original = (b"PKG_SOURCE_PROTO:=git\n"
        b"PKG_SOURCE_URL:=https://www.github.com/pymumu/smartdns.git\n"
        b"PKG_MIRROR_HASH:=5ef82ea81d5f627f52171e3b487331ecdd270554555cbff3d291590e19f4658d\n"
        b"PKG_SOURCE_VERSION:=" + CORE_COMMIT.encode() + b"\n")
    core_prepared = (b"PKG_SOURCE_VERSION:=" + CORE_COMMIT.encode() + b"\n"
        b"PKG_SOURCE:=$(PKG_NAME)-$(PKG_SOURCE_VERSION).tar.gz\n"
        b"PKG_SOURCE_URL:=https://codeload.github.com/pymumu/smartdns/tar.gz\n"
        b"PKG_SOURCE_URL_FILE:=$(PKG_SOURCE_VERSION)\n"
        b"PKG_HASH:=" + CORE_ARCHIVE_HASH.encode() + b"\n"
        b"PKG_BUILD_DIR:=$(BUILD_DIR)/$(PKG_NAME)-$(PKG_SOURCE_VERSION)\n")
    if original.count(core_original) != 1:
        raise ValueError("SmartDNS reviewed core download declaration is not unique")
    prepared = original.replace(core_original, core_prepared).replace(
        version, b"\tSOURCE_VERSION:=$(SMARTDNS_WEBUI_SOURCE_VERSION)\n"
    ).replace(
        registration,
        b"ifneq ($(filter y m,$(CONFIG_PACKAGE_smartdns-ui)),)\n" + registration + b"endif\n",
    )
    current = _read_recipe(package_dir)
    if current not in (original, prepared):
        raise ValueError("SmartDNS build source has unreviewed drift: Makefile")
    if current == prepared:
        return
    recipe = package_dir / "Makefile"
    mode = stat.S_IMODE(recipe.stat().st_mode)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".smartdns-", dir=package_dir)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(prepared)
        temporary.chmod(mode)
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
        print(f"SmartDNS compatibility error: {error}", file=sys.stderr)
        return 1
    print("SmartDNS canonical pinned core and conditional WebUI download verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
