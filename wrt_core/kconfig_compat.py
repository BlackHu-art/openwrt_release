#!/usr/bin/env python3
"""Remove two reviewed parent/feature dependency cycles in downloaded feeds."""
import argparse
import hashlib
import os
from pathlib import Path
import stat
import sys
import tempfile


# Feed revisions document the reviewed inputs, not a replacement source pin.
# Source URLs, package versions, defaults, DEPENDS and build flags stay intact.
# See tests/fixtures/kconfig-compat/sources.json for source commits and Git blobs.
QT = "feeds/video/frameworks/qt5/qt5base"
SQUEEZE = "feeds/packages/sound/squeezelite"
REVIEWED = {
    QT + "/Makefile": "a79b2c2c0b303531ca5dc83683fbb7a49a89519be828fe1b79ecc93a0be7de36",
    QT + "/Config.in": "1ad8695b21aa118824d514a0854f390b9e4859057e8b340942fe812d13be4f55",
    SQUEEZE + "/Makefile": "2502c1809fc6b32be93ee50e2eb8ec4d81cd9c2905387646352604d85719a22e",
}
EDITS = {
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


def prepare(build_dir: Path) -> None:
    """Validate all inputs before writing; repeat calls validate without edits.

    The conditional library dependencies remain in the recipes. Their propagated
    prerequisites make the parent packages depend on the feature symbols, so
    those features cannot depend on the parent as well (even via prompt/visible
    if). Unguarded options do not select the parent or its libraries. Qt still
    defaults to no OpenGL; every squeezelite feature still defaults to n.
    """
    build_dir = Path(build_dir).resolve()
    if not build_dir.is_dir():
        raise ValueError(f"build directory does not exist: {build_dir}")
    changes = []
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
        for before, after in edits:
            # Reverse only a complete known edit. An extra occurrence, partial
            # edit, changed comment or unrelated recipe change fails the hash.
            if before not in original and original.count(after) == 1:
                original = original.replace(after, before)
        if hashlib.sha256(original).hexdigest() != digest:
            raise ValueError(f"unreviewed Kconfig feed input: {relative}")
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
    print("Qt5 and squeezelite Kconfig compatibility verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
