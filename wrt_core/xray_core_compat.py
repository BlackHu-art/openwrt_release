#!/usr/bin/env python3
"""Backport fw876's UPX reuse and Naive Cronet allowance to Xray build copies.

Original: fw876/helloworld 45893d778767f3bdb2fcb6e873cf8f9a667d94d4, r2.
UPX: 20756eaad8aa61ce7168dad90b56db2d7c81063c, xray-core/Makefile only, r3.
Cronet flags: fa29e87710fef1c2eeb7c38bcca62996f0798ef2, Naive branch only, r4.
The ten original core patches and fw876r2 test-core identity remain unchanged.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile

# Validation must not create local import caches, including on rejected input.
sys.dont_write_bytecode = True
from managed_plugins import DEFAULT_SOURCES, read_lock, verify_staged


SOURCE_COMMIT = "45893d778767f3bdb2fcb6e873cf8f9a667d94d4"
UPX_COMMIT = "20756eaad8aa61ce7168dad90b56db2d7c81063c"
UPX_RECIPE_BLOB = "98f541c95e36200441a08374b9e06507e57cf64d"
CRONET_COMMIT = "fa29e87710fef1c2eeb7c38bcca62996f0798ef2"
PREPARED_RECIPE_SHA256 = "5fad25b15d48821960d87c689c08390ec3b19c3dc68efca80d61b38267b03d0c"
# SHA-256 of sorted [path, mode, sha256] triples in the reviewed source lock.
REVIEWED_FILES_SHA256 = "061fc0c4c9d353864b701cf219c225e5030fa7400abf20e453475ff2ffc8d314"
RAW = DEFAULT_SOURCES / "packages/xray-core"
ORIGINAL_INSTALL = b"""define Package/xray-core/install
	$(call GoPackage/Package/Install/Bin,$(PKG_INSTALL_DIR))
	$(INSTALL_DIR) $(1)/usr/bin/
	$(INSTALL_BIN) $(PKG_INSTALL_DIR)/usr/bin/main $(1)/usr/bin/xray
	$(STAGING_DIR_HOST)/bin/upx --lzma --best $(1)/usr/bin/xray
endef
"""
PREPARED_INSTALL = b"""define Package/xray-core/install
	$(INSTALL_DIR) $(1)/usr/bin
	$(INSTALL_BIN) $(PKG_BUILD_DIR)/.upx/xray $(1)/usr/bin/xray
endef
"""
BUILD_INSTALL = b"""# Compress once per build, not once per package/rootfs installation.
# Keep Go's output intact and let the .built stamp guard the packed copy.
define Build/Install
	$(INSTALL_DIR) $(PKG_BUILD_DIR)/.upx
	$(INSTALL_BIN) $(GO_PKG_BUILD_BIN_DIR)/main $(PKG_BUILD_DIR)/.upx/xray
	$(STAGING_DIR_HOST)/bin/upx --lzma --best $(PKG_BUILD_DIR)/.upx/xray
endef

"""


def check_go(recipe):
    """Require unique literal Go version fields before any preparation writes."""
    content = Path(recipe).read_text(encoding="utf-8")
    values = []
    for name, pattern in (("GO_VERSION_MAJOR_MINOR", r"([0-9]+)\.([0-9]+)"),
                          ("GO_VERSION_PATCH", r"([0-9]+)")):
        declarations = re.findall(r"^" + name + r"[^\S\n]*:=([^\n]*)$", content, re.MULTILINE)
        if len(declarations) != 1:
            raise ValueError(f"Go version field missing or duplicated: {name}")
        match = re.fullmatch(r"\s*" + pattern + r"\s*", declarations[0])
        if match is None:
            raise ValueError(f"Go version field is not a literal: {name}")
        values.extend(int(value) for value in match.groups())
    if tuple(values) < (1, 27, 3):
        raise ValueError("Xray 26.10.21 requires Go >= 1.27.3")


def upx_recipe(original):
    """Reproduce the full Makefile from the reviewed UPX donor."""
    anchor = b"# Go's -s -w flags strip the binary before UPX; do not strip it again.\n"
    result = original
    for old, new in ((b"PKG_RELEASE:=2\n", b"PKG_RELEASE:=3\n"),
                     (anchor, BUILD_INSTALL + anchor),
                     (ORIGINAL_INSTALL, PREPARED_INSTALL)):
        if result.count(old) != 1:
            raise ValueError("Xray reviewed Makefile backport anchor changed")
        result = result.replace(old, new)
    # Full Git blob ID matching the Xray hunk in UPX_COMMIT.
    blob = b"blob " + str(len(result)).encode() + b"\0" + result
    if hashlib.sha1(blob).hexdigest() != UPX_RECIPE_BLOB:
        raise ValueError("Xray derived Makefile differs from reviewed upstream backport")
    return result


def prepared_recipe(prior):
    """Take the exact Cronet hunk and retain the previously reviewed UPX recipe."""
    anchor = b"ifeq ($(CONFIG_XRAY_CORE_NAIVE),y)\n  GO_PKG_TAGS+=with_naive_outbound\n"
    allowance = (b"  # Cronet selects its static archive by filename, which cgo rejects by default.\n"
                 b"  GO_PKG_VARS+=CGO_LDFLAGS_ALLOW='-l:libcronet[.]a'\n")
    if prior.count(anchor) != 1 or prior.count(b"PKG_RELEASE:=3\n") != 1:
        raise ValueError("Xray reviewed Cronet backport anchor changed")
    result = prior.replace(anchor, anchor + allowance).replace(b"PKG_RELEASE:=3\n", b"PKG_RELEASE:=4\n")
    if hashlib.sha256(result).hexdigest() != PREPARED_RECIPE_SHA256:
        raise ValueError("Xray derived Makefile differs from reviewed Cronet backport")
    return result


def prepare(package_dir, go_recipe):
    """Validate the original or either complete derived tree; publish atomically."""
    check_go(go_recipe)
    package_dir = Path(package_dir)
    for protected in (DEFAULT_SOURCES, Path(__file__).resolve().parents[1] / "maintenance"):
        if package_dir.resolve().is_relative_to(protected.resolve()):
            raise ValueError("Xray original source trees cannot be modified")
    lock = read_lock(DEFAULT_SOURCES)
    entry = lock["packages"]["xray-core"]
    records = sorted((item["path"], item["mode"], item["sha256"]) for item in entry["files"])
    digest = hashlib.sha256(json.dumps(records, separators=(",", ":")).encode()).hexdigest()
    if entry["commit"] != SOURCE_COMMIT or digest != REVIEWED_FILES_SHA256:
        raise ValueError("Xray source lock differs from reviewed original tree")
    # Use the same complete source validator as the production materializer.
    verify_staged(DEFAULT_SOURCES, "xray-core", RAW)
    original = (RAW / "Makefile").read_bytes()
    prior = upx_recipe(original)
    prepared = prepared_recipe(prior)
    if package_dir.is_symlink() or not package_dir.is_dir():
        raise ValueError("Xray build source is not a regular package directory")
    recipe = package_dir / "Makefile"
    if recipe.is_symlink() or not recipe.is_file():
        raise ValueError("Xray Makefile is not a regular file")
    current = recipe.read_bytes()
    if current not in (original, prior, prepared):
        raise ValueError("Xray build source has unreviewed drift: Makefile")
    if current == original:
        verify_staged(DEFAULT_SOURCES, "xray-core", package_dir)
    else:
        # Normalize only the known derived Makefile in a disposable validation
        # copy, so the real validator still checks all file names, modes and
        # bytes, including every private-protocol patch and additional input.
        with tempfile.TemporaryDirectory(prefix="xray-verify-") as temporary:
            check = Path(temporary) / "xray-core"
            shutil.copytree(package_dir, check, symlinks=True)
            (check / "Makefile").write_bytes(original)
            verify_staged(DEFAULT_SOURCES, "xray-core", check)
        if current == prepared:
            return
    descriptor, name = tempfile.mkstemp(prefix=".xray-compat-", dir=package_dir)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(prepared)
        temporary.chmod(stat.S_IMODE(recipe.stat().st_mode))
        os.replace(temporary, recipe)
    finally:
        if temporary.exists():
            temporary.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package_dir", type=Path)
    parser.add_argument("--go-recipe", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        prepare(args.package_dir, args.go_recipe)
    except (OSError, ValueError, KeyError) as error:
        print(f"Xray compatibility error: {error}", file=sys.stderr)
        return 1
    print(f"Xray 26.10.21-r4: original tree, UPX {UPX_COMMIT}, Cronet {CRONET_COMMIT}, Go >= 1.27.3 verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
