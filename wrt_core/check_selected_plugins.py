#!/usr/bin/env python3
"""Verify selected LuCI packages and explicit package exclusions after defconfig."""

import argparse
from pathlib import Path
import re
import sys


# Uppercase/underscore suffixes are Kconfig feature switches, not package names.
PACKAGE = r"CONFIG_PACKAGE_([a-z0-9+.-]+)"
ASSIGNMENT = re.compile(rf"{PACKAGE}=([ymn])")
DISABLED = re.compile(rf"# {PACKAGE} is not set")
LUCI_PREFIXES = ("luci-app-", "luci-theme-", "luci-proto-")
DOCKER_PACKAGES = {
    "luci-app-dockerman", "luci-i18n-dockerman-zh-cn", "luci-lib-docker",
    "docker", "dockerd", "docker-compose", "containerd", "runc",
}
REMOVED_PACKAGES = {
    "luci-app-passwall", "luci-i18n-passwall-zh-cn",
    "luci-app-passwall2", "luci-i18n-passwall2-zh-cn",
}
EXCLUDED_PACKAGES = DOCKER_PACKAGES | REMOVED_PACKAGES


def selections(path: Path) -> dict[str, str]:
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if match := ASSIGNMENT.fullmatch(line.strip()):
            result[match[1]] = match[2]
        elif match := DISABLED.fullmatch(line.strip()):
            result[match[1]] = "n"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("requested", type=Path)
    parser.add_argument("resolved", type=Path)
    args = parser.parse_args()
    requested, resolved = selections(args.requested), selections(args.resolved)
    missing = [
        f"{name}: requested={value}, resolved={resolved.get(name, 'n')}"
        for name, value in requested.items()
        if name.startswith(LUCI_PREFIXES) and value != "n" and (
            resolved.get(name, "n") == "n"
            or (value == "y" and resolved.get(name) != "y")
        )
    ]
    reenabled = [
        f"{name}: requested=n, resolved={value}"
        for name, value in resolved.items()
        if name in EXCLUDED_PACKAGES and requested.get(name) == "n" and value != "n"
    ]
    if missing:
        print("ERROR: selected LuCI packages were dropped by make defconfig:", file=sys.stderr)
        print("\n".join(f"  - {item}" for item in missing), file=sys.stderr)
        print("Check feed sources, package dependencies and target support.", file=sys.stderr)
    if reenabled:
        print("ERROR: explicitly disabled packages were reenabled:", file=sys.stderr)
        print("\n".join(f"  - {item}" for item in reenabled), file=sys.stderr)
        print("Check package dependencies and per-device package lists.", file=sys.stderr)
    if missing or reenabled:
        return 1
    selected_count = sum(
        name.startswith(LUCI_PREFIXES) and value != "n"
        for name, value in requested.items()
    )
    print(f"Selected LuCI packages: {selected_count} verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
