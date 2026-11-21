#!/usr/bin/env python3
"""Execute the workflow build step without a runner or a real firmware build."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import yaml
import shell_test_helpers as shell

ROOT = Path(__file__).resolve().parents[1]


class BuildModes(unittest.TestCase):
    def invoke(self, mode):
        workflow = yaml.safe_load((ROOT / ".github/workflows/build_wrt.yml").read_text())
        step = next(s for s in workflow["jobs"]["build"]["steps"] if s.get("name") == "Build Firmware")
        with tempfile.TemporaryDirectory(prefix="workflow-build-mode-") as tmp:
            root = Path(tmp)
            entry = root / "build.sh"
            entry.write_text('#!/usr/bin/env bash\nprintf \'%s\\n\' "$@" > called.txt\n')
            entry.chmod(0o755)
            script = step["run"].replace("${{ inputs.model }}", "fixture_device")
            result = subprocess.run([shell.bash_executable(), "-c", script], cwd=root,
                env=dict(os.environ, BUILD_DEVICE="fixture_device", BUILD_MODE=mode), capture_output=True, text=True)
            called = root / "called.txt"
            return result, called.read_text().splitlines() if called.exists() else None

    def test_config_validation_stops_after_defconfig(self):
        result, arguments = self.invoke("config_only")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(arguments, ["fixture_device", "debug"])

    def test_full_build_keeps_existing_firmware_mode(self):
        result, arguments = self.invoke("firmware")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(arguments, ["fixture_device"])

    def test_unknown_build_mode_never_starts_a_build(self):
        result, arguments = self.invoke("unknown")
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(arguments)


if __name__ == "__main__":
    unittest.main()
