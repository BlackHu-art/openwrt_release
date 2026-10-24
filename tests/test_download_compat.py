#!/usr/bin/env python3
"""Exercise the reviewed upstream download recipe with real GNU make."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/download-toplevel/3fd1e27a/download.mk"
BASH = os.environ.get("BASH") or ("C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash"))
STAGES = ["tools/download", "toolchain/download", "package/download", "target/download"]


class DownloadFailurePropagation(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="download-gate-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "include").mkdir()
        self.toplevel = self.root / "include/toplevel.mk"
        self.toplevel.write_bytes(FIXTURE.read_bytes())
        (self.root / ".config").write_text("# CONFIG_PACKAGE_miniupnpd-nftables is not set\n", encoding="utf-8")
        (self.root / "Makefile").write_text('''.DEFAULT_GOAL := world
STAGING_DIR_HOST := staging
SUBMAKE = "$(MAKE)" --no-print-directory -f stages.mk
.PHONY: world FORCE tools/flock/compile tools/zstd/compile
world:
\t@printf 'compile\\n' >> calls
FORCE:
tools/flock/compile tools/zstd/compile:
\t@printf '%s\\n' '$@' >> calls
\t@mkdir -p staging/bin
\t@touch staging/bin/$(word 2,$(subst /, ,$@))
include include/toplevel.mk
''', encoding="utf-8")
        (self.root / "stages.mk").write_text('''%/download:
\t@printf '%s\\n' '$@' >> calls
\t@if [ '$(RECOVER_MIRROR)' = 1 ]; then \\
\t  printf 'curl: (22) The requested URL returned error: 404\\n'; \\
\t  printf 'Hash of the downloaded file does not match - deleting download.\\n'; \\
\tfi
\t@if [ '$@' = '$(FAIL_STAGE)' ]; then \\
\t  printf 'Hash mismatch for file fixture.tar.xz: expected good, got bad\\n'; \\
\t  exit 23; \\
\tfi
''', encoding="utf-8")

    def run_bash(self, script, **variables):
        environment = dict(os.environ, **variables)
        result = subprocess.run([BASH, "--noprofile", "--norc", "-c", script, "fixture",
                                 (ROOT / "wrt_core/modules/build_steps.sh").as_posix()],
                                cwd=self.root, env=environment, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=30)
        return result

    def build(self, **variables):
        return self.run_bash('set -euo pipefail; source "$1"; nproc() { echo 4; }; build_firmware', **variables)

    def calls(self):
        path = self.root / "calls"
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    def test_upstream_recipe_masks_package_download_failure(self):
        # Characterize the real boundary that surprised us: a later successful
        # target hides a failed recursive make in the unmodified upstream block.
        result = self.run_bash('make download -j8 V=s BUILD_LOG=1', FAIL_STAGE="package/download")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Error 23", result.stdout + result.stderr)
        self.assertEqual([item for item in self.calls() if item.endswith("/download")], STAGES)

    def test_each_download_failure_stops_later_groups_and_compile(self):
        for index, stage in enumerate(STAGES):
            with self.subTest(stage=stage):
                (self.root / "calls").unlink(missing_ok=True)
                (self.root / "logs/build-times.tsv").unlink(missing_ok=True)
                result = self.build(FAIL_STAGE=stage)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertEqual([item for item in self.calls() if item.endswith("/download")], STAGES[:index + 1])
                self.assertNotIn("compile", self.calls())
                times = (self.root / "logs/build-times.tsv").read_text(encoding="utf-8").splitlines()
                self.assertEqual(len(times), 1)
                self.assertEqual(times[0].split("\t")[::2], ["download", "2"])

    def test_success_preserves_prerequisites_order_configuration_and_repeatability(self):
        original_config = (self.root / ".config").read_bytes()
        prefix = b"# Unrelated upstream settings must remain byte-identical.\nUNCHANGED := retained\n"
        suffix = b"\nuntouched:\n\t@printf 'unrelated recipe\\n'\n"
        self.toplevel.write_bytes(prefix + FIXTURE.read_bytes() + suffix)
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = self.calls()
        self.assertEqual(set(calls[:2]), {"tools/flock/compile", "tools/zstd/compile"})
        self.assertEqual(calls[2:], STAGES + ["compile"])
        self.assertEqual((self.root / ".config").read_bytes(), original_config)
        patched = self.toplevel.read_bytes()
        self.assertTrue(patched.startswith(prefix))
        self.assertTrue(patched.endswith(suffix))
        modified = self.toplevel.stat().st_mtime_ns
        (self.root / "calls").unlink()
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.calls(), STAGES + ["compile"])
        self.assertEqual(self.toplevel.read_bytes(), patched)
        self.assertEqual(self.toplevel.stat().st_mtime_ns, modified)

    def test_recovered_mirror_errors_do_not_fail_successful_downloads(self):
        result = self.build(RECOVER_MIRROR="1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("curl: (22)", (self.root / "logs/download.log").read_text(encoding="utf-8"))
        self.assertEqual(self.calls()[-1], "compile")
        self.assertNotIn("Failure details", result.stdout + result.stderr)

    def test_unknown_or_duplicate_recipe_is_rejected_before_make_without_writes(self):
        original = FIXTURE.read_bytes()
        for contents in (original.replace(b"$(SUBMAKE) $(dir);", b"$(SUBMAKE) $(dir) || true;"),
                         original + b"\ndownload:\n\t@true\n", original + b"\t@true\n",
                         b"download:\n\t@true\n"):
            with self.subTest(contents=contents):
                self.toplevel.write_bytes(contents)
                result = self.build()
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(self.calls(), [])
                self.assertEqual(self.toplevel.read_bytes(), contents)


if __name__ == "__main__":
    unittest.main()
