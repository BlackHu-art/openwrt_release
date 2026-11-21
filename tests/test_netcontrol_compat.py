#!/usr/bin/env python3
"""Keep first-boot Netcontrol setup independent of existing Timecontrol."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from shell_test_helpers import bash_executable, bash_path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/netcontrol/61364846/luci-app-netcontrol"
HELPER = ROOT / "wrt_core/netcontrol_compat.py"
INITIALIZER = "root/etc/uci-defaults/luci-netcontrol"


def run_firstboot(source, runtime, *, matching_schema=False, fail_writes=False):
    """Execute the real initializer, replacing only the OS/service boundaries."""
    runtime = Path(runtime)
    for directory in ("etc/config", "etc/init.d", "etc/timecontrol", "usr/bin", "usr/libexec", "tmp"):
        (runtime / directory).mkdir(parents=True, exist_ok=True)
    old = runtime / "etc/config/timecontrol"
    old.write_text("config custom 'unmatched'\n option retained 'old user rule'\n")
    (runtime / "etc/timecontrol/quota").write_text("unchanged old quota\n")
    events = runtime / "events"
    for service in ("timecontrol", "netcontrol", "rpcd"):
        path = runtime / "etc/init.d" / service
        path.write_text('#!/bin/sh\nprintf "%s %s\\n" "' + service + '" "$*" >> "$EVENTS"\n')
        path.chmod(0o755)
    for executable in ("usr/bin/netcontrol", "usr/bin/netcontrolctrl", "usr/bin/netcontrol-log", "usr/libexec/netcontrol-call"):
        (runtime / executable).write_text("#!/bin/sh\nexit 0\n")
    paths = ("etc", "usr/bin", "usr/libexec", "tmp")
    for index, directory in enumerate(paths):
        source = source.replace("/" + directory + "/", f"@NETCONTROL_PATH_{index}@")
    for index, directory in enumerate(paths):
        source = source.replace(f"@NETCONTROL_PATH_{index}@", bash_path(runtime) + "/" + directory + "/")
    boundary = r'''
uci() {
    printf '%s\n' "$*" >> "$UCI_CALLS"
    [[ "$1" != -q ]] || shift
    case "$1" in
        get)
            if [[ "$MATCHING_SCHEMA" == 1 && "$2" == 'timecontrol.@timecontrol[0].enabled' ]]; then
                printf '1\n'
                return 0
            fi
            return 1 ;;
        batch) cat > "$UCI_BATCH"; return "$FAIL_WRITES" ;;
        set|add|commit) return "$FAIL_WRITES" ;;
    esac
    return 1
}
logger() { :; }
'''
    environment = dict(os.environ, EVENTS=bash_path(events), UCI_CALLS=bash_path(runtime / "uci-calls"),
                       UCI_BATCH=bash_path(runtime / "uci-batch"), MATCHING_SCHEMA=str(int(matching_schema)),
                       FAIL_WRITES="74" if fail_writes else "0", LC_ALL="C")
    result = subprocess.run([bash_executable(), "--noprofile", "--norc", "-s"],
                            input=boundary + source, env=environment,
                            capture_output=True, text=True, timeout=15)
    return result


class NetcontrolCompatibility(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="netcontrol-compat-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.package = self.root / "package"
        shutil.copytree(FIXTURE, self.package)

    def prepare(self):
        result = subprocess.run([sys.executable, "-B", str(HELPER), str(self.package)],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_firstboot_does_not_migrate_or_disable_any_existing_timecontrol_schema(self):
        # Before the adapter exists, characterize the previous raw build path.
        # This must fail on the original initializer's unconditional old stop.
        if HELPER.exists():
            self.prepare()
        source = (self.package / INITIALIZER).read_text()
        for matching, writes_fail in ((False, False), (True, True)):
            with self.subTest(matching_schema=matching, writes_fail=writes_fail):
                runtime = self.root / f"runtime-{matching}"
                result = run_firstboot(source, runtime, matching_schema=matching, fail_writes=writes_fail)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual((runtime / "etc/config/timecontrol").read_text(),
                                 "config custom 'unmatched'\n option retained 'old user rule'\n")
                self.assertEqual((runtime / "etc/timecontrol/quota").read_text(), "unchanged old quota\n")
                events = (runtime / "events").read_text().splitlines()
                self.assertFalse(any(line.startswith("timecontrol ") for line in events), events)
                self.assertIn("netcontrol enable", events)
                self.assertIn("rpcd restart", events)
                self.assertFalse((runtime / "etc/netcontrol").exists())
                config = (runtime / "etc/config/netcontrol").read_text()
                self.assertIn("option enabled '0'", config)
                self.assertIn("option chain 'forward'", config)
                self.assertIn("set ucitrack.@netcontrol[-1].init=netcontrol", (runtime / "uci-batch").read_text())

    def test_prepare_is_repeatable_and_unknown_source_is_rejected_without_changes(self):
        self.prepare()
        initializer = self.package / INITIALIZER
        before, metadata = initializer.read_bytes(), initializer.stat()
        self.prepare()
        self.assertEqual(initializer.read_bytes(), before)
        self.assertEqual(initializer.stat().st_mtime_ns, metadata.st_mtime_ns)
        self.assertEqual(initializer.stat().st_mode, metadata.st_mode)
        initializer.write_bytes(before + b"# unknown drift\n")
        unknown = initializer.read_bytes()
        result = subprocess.run([sys.executable, "-B", str(HELPER), str(self.package)],
                                capture_output=True, text=True, timeout=15)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(initializer.read_bytes(), unknown)

    def test_failed_atomic_replace_preserves_original_file_and_cleans_temporary(self):
        spec = importlib.util.spec_from_file_location("netcontrol_compat_under_test", HELPER)
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        initializer = self.package / INITIALIZER
        before, mode = initializer.read_bytes(), initializer.stat().st_mode
        with mock.patch.object(helper.os, "replace", side_effect=OSError("injected publish failure")):
            with self.assertRaises(OSError):
                helper.prepare(self.package)
        self.assertEqual(initializer.read_bytes(), before)
        self.assertEqual(initializer.stat().st_mode, mode)
        self.assertEqual(sorted(p.name for p in initializer.parent.iterdir()), ["luci-netcontrol"])

    def test_raw_fixture_and_symlink_targets_are_not_rewritten(self):
        before = (FIXTURE / INITIALIZER).read_bytes()
        result = subprocess.run([sys.executable, "-B", str(HELPER), str(FIXTURE)],
                                capture_output=True, text=True, timeout=15)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((FIXTURE / INITIALIZER).read_bytes(), before)
        if os.name != "nt":
            initializer = self.package / INITIALIZER
            initializer.unlink()
            initializer.symlink_to(FIXTURE / INITIALIZER)
            result = subprocess.run([sys.executable, "-B", str(HELPER), str(self.package)],
                                    capture_output=True, text=True, timeout=15)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(initializer.is_symlink())
            self.assertEqual((FIXTURE / INITIALIZER).read_bytes(), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
