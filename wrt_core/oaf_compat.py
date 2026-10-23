#!/usr/bin/env python3
"""Prepare reviewed OAF 7 build copies without changing the managed snapshot.

The service remains available after the user's documented manual enable/start.
Existing runtime configuration is never rewritten or migrated by this helper.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile


RAW = Path(__file__).resolve().parent / "managed/packages"
REVIEWED = {
    "open-app-filter/Makefile": "2fad26432f7e6f92992a738b78392150860cccecd0c58f0614caa91ca90b8f7e",
    "open-app-filter/files/appfilter.init": "2dbb2aa8afc319cece9a75b8b2a9cc5dcb359bea8e0bcb9ad607ce86ec4390b4",
    "open-app-filter/files/luci-app-oaf.json": "d84fc70179ed6991065d197166a64a6379551b284df6b34b44d9f0d90d10931a",
    "luci-app-oaf/root/usr/share/rpcd/acl.d/luci-app-oaf.json": "0363c412fe1d964ec07564f9d49a098451773078677bacb409aaef36835c92ed",
}
FIRSTBOOT = b'''#!/bin/sh
# Preserve explicit choices; never rewrite or migrate existing UCI files.
# OAF remains available through the documented manual service enable/start.
if [ "$(uci -q get fwx.appfilter.enable)" = "0" ] &&
   [ "$(uci -q get fwx.macfilter.enable)" = "0" ] &&
   [ "$(uci -q get fwx.record.enable)" = "0" ]; then
    /etc/init.d/appfilter disable
    /etc/init.d/appfilter stop
fi
exit 0
'''


def _read(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"OAF source is missing or not a regular file: {path}")
    return path.read_bytes()


def _reviewed_inputs():
    inputs = {}
    for relative, expected in REVIEWED.items():
        data = _read(RAW / relative)
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError(f"OAF managed source has unreviewed drift: {relative}")
        inputs[relative] = data
    return inputs


def _prepared_payloads(inputs):
    initializer = inputs["open-app-filter/files/appfilter.init"]
    pattern = rb"(?ms)(^[ \t]*ensure_config_file /etc/config/fwx <<'EOF'\n)(.*?)(^EOF\n)"
    match = re.search(pattern, initializer)
    if not match:
        raise ValueError("OAF reviewed initializer has no unique fwx default block")
    config, count = re.subn(rb"(?m)^(\toption enable )'?1'?$", rb"\g<1>'0'", match[2])
    if count != 3 or config.count(b"\toption disable_hnat '0'\n") != 1:
        raise ValueError("OAF reviewed default schema changed")
    initializer = initializer[:match.start(2)] + config + initializer[match.end(2):]

    recipe = inputs["open-app-filter/Makefile"]
    anchor = b"\t$(INSTALL_DIR) $(1)/etc/config\n"
    if recipe.count(anchor) != 1:
        raise ValueError("OAF reviewed installation rule changed")
    recipe = recipe.replace(anchor, anchor +
                            b"\t$(INSTALL_CONF) ./files/fwx $(1)/etc/config/fwx\n"
                            b"\t$(INSTALL_DIR) $(1)/etc/uci-defaults\n"
                            b"\t$(INSTALL_BIN) ./files/99_disable_oaf $(1)/etc/uci-defaults/99_disable_oaf\n")
    backend_acl = json.loads(inputs["open-app-filter/files/luci-app-oaf.json"])
    luci_acl = json.loads(inputs["luci-app-oaf/root/usr/share/rpcd/acl.d/luci-app-oaf.json"])
    if backend_acl.keys() & luci_acl.keys():
        raise ValueError("OAF ACL groups overlap and require a reviewed permission merge")
    acl = (json.dumps(dict(backend_acl, **luci_acl), ensure_ascii=False, indent=2) + "\n").encode()
    return {
        "open-app-filter/Makefile": (recipe, 0o644),
        "open-app-filter/files/appfilter.init": (initializer, 0o755),
        "open-app-filter/files/luci-app-oaf.json": (acl, 0o644),
        "open-app-filter/files/fwx": (config, 0o644),
        "open-app-filter/files/99_disable_oaf": (FIRSTBOOT, 0o755),
    }


def prepare(appfilter_dir, luci_dir):
    """Validate all reviewed bytes, then publish deterministic build-copy fixes.

    Only complete original or complete prepared states are accepted. A partial
    preparation or unknown file never triggers another mutation. Runtime config
    creation still uses upstream's existing-file guard and no UCI setters.
    """
    appfilter_dir, luci_dir = Path(appfilter_dir), Path(luci_dir)
    roots = {"open-app-filter": appfilter_dir, "luci-app-oaf": luci_dir}
    for root in roots.values():
        resolved = root.resolve()
        if resolved.is_relative_to(RAW.resolve()) or not root.is_dir():
            raise ValueError(f"OAF preparation requires a separate build copy: {root}")
    if appfilter_dir.resolve().is_relative_to(luci_dir.resolve()) or luci_dir.resolve().is_relative_to(appfilter_dir.resolve()):
        raise ValueError("OAF build package roots must be separate")

    def target(relative):
        package, remainder = relative.split("/", 1)
        path = roots[package] / remainder
        # Directory symlinks from src-link feeds are valid, but an individual
        # payload or nested directory must never redirect writes outside its package.
        if not path.resolve().is_relative_to(roots[package].resolve()) or path.is_symlink():
            raise ValueError(f"OAF payload follows an unexpected symlink: {path}")
        return path

    inputs = _reviewed_inputs()
    outputs = _prepared_payloads(inputs)
    removed = "luci-app-oaf/root/usr/share/rpcd/acl.d/luci-app-oaf.json"
    paths = set(inputs) | set(outputs)
    actual = {relative: (_read(target(relative)) if target(relative).exists() else None)
              for relative in paths}
    original = dict(inputs, **{relative: None for relative in outputs if relative not in inputs})
    prepared = {relative: data for relative, (data, _) in outputs.items()}
    prepared[removed] = None
    if actual == prepared:
        if os.name != "nt":
            for relative, (_, mode) in outputs.items():
                if target(relative).stat().st_mode & 0o777 != mode:
                    raise ValueError(f"OAF prepared file has unreviewed mode drift: {relative}")
        return {"changed": False, "schema": "fwx-v7"}
    if actual != original:
        changed = sorted(relative for relative in paths if actual[relative] != original.get(relative))
        raise ValueError("OAF source drift or partial preparation; no files changed: " + ", ".join(changed))

    staged = []
    try:
        # Stage every output before replacing any input or removing the duplicate ACL.
        for relative, (data, mode) in outputs.items():
            destination = target(relative)
            with tempfile.NamedTemporaryFile(prefix=".oaf-compat-", dir=destination.parent, delete=False) as stream:
                temporary = Path(stream.name)
                staged.append((temporary, destination))
                stream.write(data)
            temporary.chmod(mode)
        for temporary, destination in staged:
            os.replace(temporary, destination)
        target(removed).unlink()
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)
    return {"changed": True, "schema": "fwx-v7"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("appfilter_dir", type=Path)
    parser.add_argument("luci_dir", type=Path)
    arguments = parser.parse_args()
    try:
        result = prepare(arguments.appfilter_dir, arguments.luci_dir)
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print("OAF 7 compatibility " + ("prepared" if result["changed"] else "verified"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
