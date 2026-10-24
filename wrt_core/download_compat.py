#!/usr/bin/env python3
"""Preserve failed recursive download statuses in the reviewed upstream recipe."""
import argparse
import os
from pathlib import Path
import re
import stat
import sys
import tempfile


# VIKINGYFY/immortalwrt 3fd1e27a511851b41cf082b067b60099e8e026c4,
# include/toplevel.mk:198-205. Keep SDK handling and host-tool prerequisites.
ORIGINAL = b'''ifndef SDK
  DOWNLOAD_DIRS = tools/download toolchain/download package/download target/download
else
  DOWNLOAD_DIRS = package/download
endif

download: .config FORCE $(if $(wildcard $(STAGING_DIR_HOST)/bin/flock),,tools/flock/compile) $(if $(wildcard $(STAGING_DIR_HOST)/bin/zstd),,tools/zstd/compile)
\t@+$(foreach dir,$(DOWNLOAD_DIRS),$(SUBMAKE) $(dir);)
'''
REPAIRED = ORIGINAL.replace(b"$(SUBMAKE) $(dir);", b"$(SUBMAKE) $(dir) || exit $$?;")


def prepare_download(build_root):
    """Change only the known download block; reject drift and accept repeat runs."""
    target = Path(build_root) / "include/toplevel.mk"
    if target.is_symlink() or not target.is_file():
        raise ValueError("download recipe is missing or redirected: " + str(target))
    current = target.read_bytes()
    rules = re.findall(rb"(?m)^download[ \t]*::?[^\n]*\n(?:[ \t]*\n|\t[^\n]*\n)*", current)
    known_rules = {block[block.index(b"download:"):].rstrip(b"\n") for block in (ORIGINAL, REPAIRED)}
    if (current.count(ORIGINAL) + current.count(REPAIRED) != 1
            or len(rules) != 1 or rules[0].rstrip(b"\n") not in known_rules):
        raise ValueError("unreviewed or duplicate download recipe in " + str(target))
    if REPAIRED in current:
        return
    prepared = current.replace(ORIGINAL, REPAIRED, 1)
    descriptor, staged = tempfile.mkstemp(prefix=".download-compat-", dir=target.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(prepared)
        os.chmod(staged, stat.S_IMODE(target.stat().st_mode))
        os.replace(staged, target)
    finally:
        Path(staged).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build_root", type=Path)
    args = parser.parse_args()
    try:
        prepare_download(args.build_root)
    except (OSError, ValueError) as error:
        print("Download preparation rejected: " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
