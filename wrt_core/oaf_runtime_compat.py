#!/usr/bin/env python3
"""Apply reviewed OAF runtime safety fixes only to separate build copies.

The managed package bytes, package selection, versions and sources remain the
reviewed baseline. Default-off/service/ACL preparation stays in oaf_compat.py.
"""
import argparse
import hashlib
import os
from pathlib import Path
import re
import sys
import tempfile


ROOT = Path(__file__).resolve().parent
RAW = ROOT / "managed/packages"
PATCH = ROOT / "patches/oaf-runtime-safety.patch"
PATCH_SHA256 = "d67b7ac294074edbe9539f5099e267cc82db2f6f409a5df08845c01e30a57ca6"
REVIEWED = {
    "oaf/src/fwx_main.c": "daf59e7fa8173f047e8b82a05f71bc297f159b606bd55b8bce2a071084957750",
    "open-app-filter/src/main.c": "e0ea3ab83ab3f60612244172fe8e7b78828fc8d4e31c4aafd21e41aff307bdfb",
}


def _read(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"OAF runtime source is missing or not a regular file: {path}")
    return path.read_bytes()


def _patched(inputs, patch):
    """Apply the reviewed, hash-checked unified hunks with exact context only.

    No offsets, fuzz, external patch executable or source-tree mutation. All
    hunk counts and file names are checked before producing output bytes.
    """
    lines = patch.splitlines(keepends=True)
    outputs = dict(inputs)
    seen = set()
    relative = None
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith(b"diff --git "):
            relative = None
        elif line.startswith(b"--- a/"):
            old = line[6:].rstrip(b"\r\n").decode("utf-8")
            index += 1
            if index >= len(lines) or lines[index] != ("+++ b/" + old + "\n").encode():
                raise ValueError("OAF runtime patch has mismatched file headers")
            if old not in inputs or old in seen:
                raise ValueError("OAF runtime patch has an unreviewed or duplicate path")
            relative = old
            seen.add(relative)
        elif line.startswith(b"@@ "):
            header = re.match(rb"@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@", line)
            if relative is None or not header:
                raise ValueError("OAF runtime patch has an invalid hunk header")
            old_count, new_count = (int(value) if value is not None else 1 for value in header.groups())
            before, after = [], []
            consumed_old = consumed_new = 0
            while consumed_old < old_count or consumed_new < new_count:
                index += 1
                if index >= len(lines) or lines[index][:1] not in (b" ", b"-", b"+"):
                    raise ValueError("OAF runtime patch has a truncated hunk")
                marker, body = lines[index][:1], lines[index][1:]
                if marker in (b" ", b"-"):
                    before.append(body)
                    consumed_old += 1
                if marker in (b" ", b"+"):
                    after.append(body)
                    consumed_new += 1
            if (consumed_old, consumed_new) != (old_count, new_count):
                raise ValueError("OAF runtime patch hunk counts do not match")
            old_bytes, new_bytes = b"".join(before), b"".join(after)
            if not old_bytes or outputs[relative].count(old_bytes) != 1:
                raise ValueError(f"OAF runtime patch context is not unique: {relative}")
            outputs[relative] = outputs[relative].replace(old_bytes, new_bytes, 1)
        elif line.strip():
            raise ValueError("OAF runtime patch has an unsupported record")
        index += 1
    if seen != set(inputs) or any(outputs[name] == inputs[name] for name in inputs):
        raise ValueError("OAF runtime patch does not cover all reviewed inputs")
    return outputs


def _payloads():
    inputs = {}
    for relative, expected in REVIEWED.items():
        data = _read(RAW / relative)
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError(f"OAF managed source has unreviewed drift: {relative}")
        inputs[relative] = data
    patch = _read(PATCH)
    if hashlib.sha256(patch).hexdigest() != PATCH_SHA256:
        raise ValueError("OAF runtime patch has unreviewed drift")
    return inputs, _patched(inputs, patch)


def prepare(oaf_dir, appfilter_dir, *, check_only=False):
    """Prepare both C files transactionally, accepting complete states only.

    Call separately from oaf_compat.prepare(appfilter_dir, luci_dir), in either
    order. There are no overlapping payloads or runtime configuration writes.
    Staging or publication exceptions restore the previously complete state.
    """
    roots = {"oaf": Path(oaf_dir), "open-app-filter": Path(appfilter_dir)}
    resolved = [root.resolve() for root in roots.values()]
    for root, location in zip(roots.values(), resolved):
        if not root.is_dir() or location.is_relative_to(RAW.resolve()):
            raise ValueError(f"OAF runtime preparation requires a separate build copy: {root}")
    if resolved[0].is_relative_to(resolved[1]) or resolved[1].is_relative_to(resolved[0]):
        raise ValueError("OAF runtime build package roots must be separate")

    def target(relative):
        package, remainder = relative.split("/", 1)
        path = roots[package] / remainder
        if path.is_symlink() or not path.resolve().is_relative_to(roots[package].resolve()):
            raise ValueError(f"OAF runtime payload follows an unexpected symlink: {path}")
        return path

    original, prepared = _payloads()
    actual = {relative: _read(target(relative)) for relative in original}
    if actual == prepared:
        return {"changed": False, "needs_update": False, "patch": "oaf-runtime-safety"}
    if actual != original:
        changed = sorted(relative for relative in actual if actual[relative] != original[relative])
        raise ValueError("OAF runtime source drift or partial preparation; no files changed: " + ", ".join(changed))
    if check_only:
        return {"changed": False, "needs_update": True, "patch": "oaf-runtime-safety"}

    temporary_paths = []
    staged = {}
    backups = {}
    published = []
    try:
        # Prepare replacements and rollback bytes before publishing any change.
        for relative in original:
            destination = target(relative)
            mode = destination.stat().st_mode & 0o777
            for mapping, data in ((staged, prepared[relative]), (backups, original[relative])):
                with tempfile.NamedTemporaryFile(prefix=".oaf-runtime-", dir=destination.parent, delete=False) as stream:
                    temporary = Path(stream.name)
                    temporary_paths.append(temporary)
                    stream.write(data)
                temporary.chmod(mode)
                mapping[relative] = temporary
        try:
            for relative in original:
                os.replace(staged[relative], target(relative))
                published.append(relative)
        except OSError:
            for relative in reversed(published):
                os.replace(backups[relative], target(relative))
            raise
    finally:
        for temporary in temporary_paths:
            temporary.unlink(missing_ok=True)
    return {"changed": True, "needs_update": False, "patch": "oaf-runtime-safety"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("oaf_dir", type=Path)
    parser.add_argument("appfilter_dir", type=Path)
    parser.add_argument("--check-only", action="store_true", help="validate all inputs and target states without writing")
    arguments = parser.parse_args()
    try:
        result = prepare(arguments.oaf_dir, arguments.appfilter_dir, check_only=arguments.check_only)
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print("OAF runtime safety " + ("preflight passed" if arguments.check_only else
                                  "prepared" if result["changed"] else "verified"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
