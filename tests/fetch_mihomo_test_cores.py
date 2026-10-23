#!/usr/bin/env python3
"""Explicitly fetch official old/new Mihomo for config-only compatibility tests.

Asset SHA-256 values are the published GitHub release API digests for v1.19.30
and v1.19.33. No download or core execution happens on import. These binaries
are test inputs only; this does not replace the firmware's selected core.
"""
import argparse
import gzip
import hashlib
import os
from pathlib import Path
import platform
import stat
import tempfile
import time
import urllib.request
import zipfile

VERSIONS = {"old": "1.19.30", "new": "1.19.33"}
DIGESTS = {
    "linux": {
        "old": "cbe553d0319a414bd3a372c5976a252155b2c4882b66bce88a4d6bba9571a553",
        "new": "8ec92e7b2fdc6b853ba00156bab7e4e965c8b0d843b8c4ac8ab98795f02ad524",
    },
    "windows": {
        "old": "8b81fe2c5cd04ca6deb61eec6075150b44cc5ad13ab867750642e2422f7c1278",
        "new": "fb0b960eff568459502d4ebe53e9cca203053d86ec9024fe935f19615d74d9aa",
    },
}
MAX_BYTES = 64 * 1024 * 1024


def fetch_core(output, generation, system):
    version = VERSIONS[generation]
    suffix = ".zip" if system == "windows" else ".gz"
    name = f"mihomo-{system}-amd64-v1-v{version}"
    url = f"https://github.com/MetaCubeX/mihomo/releases/download/v{version}/{name}{suffix}"
    destination = Path(output).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "openwrt-release-core-tests"})
    with tempfile.TemporaryDirectory(prefix="mihomo-test-", dir=destination.parent) as temporary:
        digest, total, started = hashlib.sha256(), 0, time.monotonic()
        archive = Path(temporary) / ("release" + suffix)
        with urllib.request.urlopen(request, timeout=30) as response, archive.open("wb") as target:
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_BYTES or time.monotonic() - started > 120:
                    raise ValueError("Mihomo asset exceeds the bounded download budget")
                digest.update(chunk)
                target.write(chunk)
        if digest.hexdigest() != DIGESTS[system][generation]:
            raise ValueError("Mihomo archive SHA-256 mismatch")
        if system == "windows":
            with zipfile.ZipFile(archive) as source:
                # Read exactly one known root member, without extracting paths.
                entry = source.getinfo("mihomo-windows-amd64-v1.exe")
                if entry.is_dir() or stat.S_ISLNK(entry.external_attr >> 16) or entry.file_size > MAX_BYTES:
                    raise ValueError("invalid Mihomo archive member")
                executable = source.read(entry)
        else:
            with gzip.open(archive, "rb") as source:
                executable = source.read(MAX_BYTES + 1)
        if len(executable) > MAX_BYTES:
            raise ValueError("Mihomo executable exceeds the bounded budget")
        staged = Path(temporary) / "mihomo"
        staged.write_bytes(executable)
        staged.chmod(0o755)
        os.replace(staged, destination)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generation", choices=VERSIONS, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    system = platform.system().lower()
    if system not in DIGESTS or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise ValueError("only official Linux/Windows amd64-v1 assets are pinned")
    output = fetch_core(args.output, args.generation, system)
    print(f"Mihomo {VERSIONS[args.generation]}; archive SHA-256={DIGESTS[system][args.generation]}")
    print(output)


if __name__ == "__main__":
    main()
