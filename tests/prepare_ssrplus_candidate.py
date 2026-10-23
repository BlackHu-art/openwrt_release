#!/usr/bin/env python3
"""Render the current fw876 integration from managed source; never contact a router."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True,
                        help="a new directory; an existing directory is never overwritten")
    options = parser.parse_args()
    output = options.output.resolve()
    if output.exists():
        parser.error("output already exists: " + str(output))
    shutil.copytree(ROOT / "wrt_core/managed/packages/luci-app-ssr-plus", output)
    bash = ("C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash"))
    environment = os.environ.copy()
    environment.pop("MSYS_NO_PATHCONV", None)
    # All source operations use positional paths, never interpolated shell code.
    result = subprocess.run([
        bash, "--noprofile", "--norc", "-c",
        'BASE_PATH=$1; source "$BASE_PATH/modules/plugin_compat.sh"; fix_ssrplus_compat "$2"',
        "ssrplus-candidate", (ROOT / "wrt_core").as_posix(), output.as_posix()],
        env=environment, cwd=ROOT)
    if result.returncode:
        print("Candidate generation failed; directory retained for diagnosis: " + str(output), file=sys.stderr)
        return result.returncode
    print("Public source candidate: " + str(output / "root"))
    print("Manifest: " + str(output / "root/usr/share/shadowsocksr/ssrplus-build.json"))
    print("No router access, package compilation, deployment or service restart performed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
