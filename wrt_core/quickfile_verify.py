#!/usr/bin/env python3
"""Require QuickFile's target Rust installation contract before using its source."""
from pathlib import Path
import re
import sys


def verify_recipe(text):
    def field(name):
        values = re.findall(r"^" + name + r"\s*:=\s*(.*?)\s*$", text, re.M)
        if len(values) != 1:
            raise ValueError(f"QuickFile requires one {name} declaration")
        return values[0]

    if field("PKG_NAME") != "quickfile":
        raise ValueError("unexpected QuickFile package name")
    if field("PKG_SOURCE") != "quickfile-src-$(PKG_VERSION).tar.xz":
        raise ValueError("QuickFile must use the reviewed source archive format")
    if not re.fullmatch(r"[0-9a-f]{64}", field("PKG_HASH")):
        raise ValueError("QuickFile source archive requires a SHA-256 hash")
    if "rust/host" not in field("PKG_BUILD_DEPENDS").split():
        raise ValueError("QuickFile requires the target Rust build dependency")
    if "feeds/packages/lang/rust/rust-package.mk" not in text or "$(RUST_ARCH_DEPENDS)" not in text:
        raise ValueError("QuickFile target Rust architecture rules are missing")
    blocks = re.findall(r"^define Package/quickfile/install\n(.*?)^endef\s*$", text, re.M | re.S)
    if len(blocks) != 1:
        raise ValueError("QuickFile installation block changed; review its source recipe")
    installs = re.findall(r"^\s*\$\(INSTALL_BIN\)\s+(.+)$", blocks[0], re.M)
    core = "$(PKG_INSTALL_DIR)/bin/quickfile $(1)/usr/bin/"
    if installs.count(core) != 1 or any("ARCH_PACKAGES" in line or "quickfile-" in line for line in installs):
        raise ValueError("QuickFile must install the target Rust output; prebuilt architecture rewrites are unsupported")


def main():
    try:
        verify_recipe(Path(sys.argv[1]).read_text(encoding="utf-8"))
    except (OSError, ValueError, IndexError) as error:
        print(f"QuickFile source error: {error}", file=sys.stderr)
        return 1
    print("QuickFile target Rust recipe verified; original install rule retained")
    return 0


if __name__ == "__main__":
    sys.exit(main())
