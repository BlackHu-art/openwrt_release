#!/usr/bin/env python3
"""Explicitly fetch the pinned official Xray executable for config-only tests.

No download happens on import. The minimum version required by the imported
Passwall generators is an official prerelease, not an upstream stable release.
"""
import argparse
import hashlib
import os
from pathlib import Path
import platform
import stat
import tempfile
import time
import urllib.request
import zipfile


VERSION = "26.7.11"
ASSETS = {
    "linux-amd64": ("Xray-linux-64.zip", "xray",
                    "aa11c3685c71da0ffc71e511db50404609e7e963bb914b048f59a6a00af8930e"),
    "windows-amd64": ("Xray-windows-64.zip", "xray.exe",
                      "af801b62c4d41d248d3db8016d4c6e2a7ccfb7ed443e3738aeb6f9e062321512"),
}
MAX_BYTES = 64 * 1024 * 1024


def host_platform():
    if platform.machine().lower() not in {"amd64", "x86_64"}:
        raise ValueError("only official Linux/Windows amd64 assets are pinned")
    selected = platform.system().lower() + "-amd64"
    if selected not in ASSETS:
        raise ValueError("unsupported host platform: " + selected)
    return selected


def fetch_core(output, selected_platform):
    asset, member, expected_sha256 = ASSETS[selected_platform]
    url = "https://github.com/XTLS/Xray-core/releases/download/v" + VERSION + "/" + asset
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="xray-test-download-", dir=output.parent) as temporary:
        archive = Path(temporary) / "release.zip"
        digest = hashlib.sha256()
        total = 0
        started = time.monotonic()
        request = urllib.request.Request(url, headers={"User-Agent": "openwrt-release-core-tests"})
        with urllib.request.urlopen(request, timeout=30) as response, archive.open("wb") as target:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_BYTES or time.monotonic() - started > 120:
                    raise ValueError("Xray asset exceeds the bounded download budget")
                digest.update(chunk)
                target.write(chunk)
        actual = digest.hexdigest()
        if actual != expected_sha256:
            raise ValueError("Xray archive SHA-256 mismatch: " + actual)
        # Read one exact root entry; never extract archive-controlled paths.
        with zipfile.ZipFile(archive) as source:
            entry = source.getinfo(member)
            if entry.is_dir() or stat.S_ISLNK(entry.external_attr >> 16) or entry.file_size > MAX_BYTES:
                raise ValueError("invalid executable archive entry")
            executable = source.read(entry)
        staged = Path(temporary) / member
        staged.write_bytes(executable)
        staged.chmod(0o755)
        os.replace(staged, output)
    return output, expected_sha256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="exact executable destination")
    parser.add_argument("--platform", choices=ASSETS, help="default: current amd64 host")
    args = parser.parse_args()
    output, digest = fetch_core(args.output, args.platform or host_platform())
    print("Xray " + VERSION + " (official prerelease); archive SHA-256=" + digest)
    print(output)


if __name__ == "__main__":
    main()
