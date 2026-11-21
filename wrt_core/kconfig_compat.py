#!/usr/bin/env python3
"""Repair reviewed feed configuration dependency cycles in build copies."""
import argparse
import hashlib
import os
from pathlib import Path
import stat
import sys
import tempfile


# Feed revisions document the reviewed inputs, not a replacement source pin.
# Source URLs, package versions, defaults and build flags stay intact.
# The reviewed GnuPG2 repair adds the missing runtime auto-selection only.
# See tests/fixtures/kconfig-compat/sources.json for source commits and Git blobs.
QT = "feeds/video/frameworks/qt5/qt5base"
SQUEEZE = "feeds/packages/sound/squeezelite"
GNUPG2 = "feeds/packages/utils/gnupg2"
REVIEWED = {
    QT + "/Makefile": "a79b2c2c0b303531ca5dc83683fbb7a49a89519be828fe1b79ecc93a0be7de36",
    QT + "/Config.in": "1ad8695b21aa118824d514a0854f390b9e4859057e8b340942fe812d13be4f55",
    SQUEEZE + "/Makefile": "2502c1809fc6b32be93ee50e2eb8ec4d81cd9c2905387646352604d85719a22e",
    GNUPG2 + "/Makefile": "d8738125146f448507f317fab0bb6e1673e355c3a4a1e5d5c1f132dd3ebae6e6",
}
# Exact additional recipes from the independently reviewed master, 25.12 and
# 24.10 feed snapshots. These retain their own versions, source hashes,
# conflict declarations and packaging fixes. Only the reviewed parent/feature
# guards and GnuPG2 runtime dependency below are adapted; other drift fails.
# Full bytes and provenance are recorded under fixtures/kconfig-compat/variants.
REVIEWED_VARIANTS = {
    GNUPG2 + "/Makefile": (
        "0987f5dfd1f26e4505f1cd0796de32f19d1e88ef5237c71a15b9a5e71f4239c2",
    ),
    QT + "/Makefile": (
        "e615c8343db4695e0c9059f699d969f1d5c9c21e3931add4b6c026dc277e0bb4",
    ),
    SQUEEZE + "/Makefile": (
        "ce2ca21722e6a0547c291aa4aa1947e19fde6ab533e9109a3ce8844a947dcf08",
        "3ac165e84a5fb1ea57cecae1b1dbfef8dbaa97dd012faf7e06128399f71464b6",
        "67525c5f8b5ee6dbcba1bb4f42bcea6cdc34346d2bc6072db77bf21a2e792c5f",
    ),
}
EDITS = {
    GNUPG2 + "/Makefile": (
        # Upstream issue 31215: a non-select runtime prerequisite propagates the
        # optional fwknop GPG condition into LuCI and closes its parent loop.
        # Let the utilities pull in their required runtime; preserve all fwknop
        # feature guards/defaults and conditional libraries in the original form.
        (b'define Package/gnupg2-utils\n  $(call Package/gnupg2/Default)\n  DEPENDS:=gnupg2 +libcurl\n',
         b'define Package/gnupg2-utils\n  $(call Package/gnupg2/Default)\n  DEPENDS:=+gnupg2 +libcurl\n'),
    ),
    QT + "/Config.in": (
        (b'    default BUILD_qt5base-gui_OPENGL_NONE\n    depends on PACKAGE_qt5base-gui\n',
         b'    default BUILD_qt5base-gui_OPENGL_NONE\n'),
    ),
    SQUEEZE + "/Makefile": (
        (b'define Package/squeezelite-custom/config\n\tif PACKAGE_squeezelite-custom\n',
         b'define Package/squeezelite-custom/config\n\tmenu "Squeezelite custom options"\n'),
        (b'\t\t\tWMA and ALAC codec support\n\t\t    default n\n\tendif\n',
         b'\t\t\tWMA and ALAC codec support\n\t\t    default n\n\tendmenu\n'),
    ),
}
QT_DRM_EDIT = (
    b'config BUILD_qt5base-gui_DRM\n    bool "Include DRM support"\n    depends on PACKAGE_qt5base-gui\n',
    b'config BUILD_qt5base-gui_DRM\n    bool "Include DRM support"\n',
)


def prepare(build_dir: Path) -> None:
    """Validate all inputs before writing; repeat calls validate without edits.

    The conditional library dependencies remain in the recipes. Their propagated
    prerequisites make the parent packages depend on the feature symbols, so
    those features cannot depend on the parent as well (even via prompt/visible
    if). Unguarded options do not select the parent or its libraries. Qt still
    defaults to no OpenGL; every squeezelite feature still defaults to n.
    GnuPG2 utilities select their required runtime, avoiding a propagated
    fwknop feature prerequisite without changing fwknop's parent guards.
    """
    build_dir = Path(build_dir).resolve()
    if not build_dir.is_dir():
        raise ValueError(f"build directory does not exist: {build_dir}")
    changes = []
    modern_qt = False
    for relative, digest in REVIEWED.items():
        path = build_dir / relative
        package = path.parent
        if not package.exists() and not package.is_symlink():
            continue
        if (not path.is_file() or path.is_symlink()
                or not path.resolve().is_relative_to(build_dir)
                or any(p.is_symlink() for p in path.parents if p != build_dir and build_dir in p.parents)):
            raise ValueError(f"Kconfig input is not a build-local regular file: {relative}")
        content = path.read_bytes()
        original = content
        edits = EDITS.get(relative, ())
        if modern_qt and relative == QT + "/Config.in":
            # The reviewed new linuxfb recipe adds a conditional DRM library.
            # Its propagated prerequisites create the same parent/feature loop
            # as OpenGL. Keep the library dependency and unguard the feature.
            edits += (QT_DRM_EDIT,)
        for before, after in edits:
            # Reverse only a complete known edit. An extra occurrence, partial
            # edit, changed comment or unrelated recipe change fails the hash.
            if before not in original and original.count(after) == 1:
                original = original.replace(after, before)
        identity = hashlib.sha256(original).hexdigest()
        if identity not in (digest, *REVIEWED_VARIANTS.get(relative, ())):
            raise ValueError(f"unreviewed Kconfig feed input: {relative}")
        if relative == QT + "/Makefile":
            modern_qt = identity in REVIEWED_VARIANTS[relative]
        prepared = original
        for before, after in edits:
            if prepared.count(before) != 1:
                raise ValueError(f"reviewed Kconfig edit is not unique: {relative}")
            prepared = prepared.replace(before, after)
        if content not in (original, prepared):
            raise ValueError(f"partially applied Kconfig compatibility edit: {relative}")
        if prepared != content:
            changes.append((path, content, prepared))
    staged = []
    replaced = []
    try:
        # Stage every replacement before changing a source file. Validation or
        # staging failures leave both sources untouched; commit failures roll back.
        for path, original, prepared in changes:
            descriptor, name = tempfile.mkstemp(prefix=".kconfig-compat-", dir=path.parent)
            temporary = Path(name)
            staged.append((path, original, temporary))
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(prepared)
            temporary.chmod(stat.S_IMODE(path.stat().st_mode))
        for path, original, temporary in staged:
            os.replace(temporary, path)
            replaced.append((path, original))
    except OSError:
        for path, original in reversed(replaced):
            path.write_bytes(original)
        raise
    finally:
        for _, _, temporary in staged:
            if temporary.exists():
                temporary.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build_dir", type=Path)
    args = parser.parse_args(argv)
    try:
        prepare(args.build_dir)
    except (OSError, ValueError) as error:
        print(f"Kconfig compatibility error: {error}", file=sys.stderr)
        return 1
    print("Qt5, squeezelite and fwknop/GnuPG2 Kconfig compatibility verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
