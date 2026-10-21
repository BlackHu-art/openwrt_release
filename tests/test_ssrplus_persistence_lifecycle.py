#!/usr/bin/env python3
"""Exercise the imported ssr-rules shell, replacing only OS operations.

The official fixture stays byte-for-byte intact.  The lifecycle patch depends
on the earlier metadata/atomic-export patch.  Linux acceptance separately uses
real flock, /proc, nft and a fresh network namespace.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/ssrplus-persistence/2abdc9aa/ssr-rules"
PATCHES = [ROOT / "wrt_core/patches" / name for name in (
    "ssrplus-persistence.patch", "ssrplus-persistence-lifecycle.patch")]
INET = """table inet ss_spec {
    set whitelist {
        type ipv4_addr
        flags interval
        elements = { 192.0.2.1 }
    }
    chain ss_spec_wan_fw {
        tcp dport 443 redirect to :1234
    }
    chain ss_spec_wan_ac {
        meta l4proto tcp jump ss_spec_wan_fw
    }
    chain prerouting {
        type nat hook prerouting priority dstnat; policy accept;
        meta l4proto tcp jump ss_spec_wan_ac
    }
}
"""
MANGLE = """table ip ss_spec_mangle {
    chain prerouting {
        type filter hook prerouting priority mangle; policy accept;
    }
}
"""


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ssrp-lifecycle-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.bash = os.environ.get("BASH") or (
            "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash"))
        self.env = os.environ.copy()
        self.env.update(TEST_ROOT=self.base.as_posix(), MSYS_NO_PATHCONV="1")
        self.source = self.base / "root/usr/bin/ssr-rules"
        self.source.parent.mkdir(parents=True)
        shutil.copyfile(FIXTURE, self.source)
        for patch in PATCHES:
            if patch.exists() and not (patch == PATCHES[1] and
                                       os.environ.get("SSR_LIFECYCLE_UNPATCHED")):
                self.shell('git -C "$1" apply "$2"', self.base.as_posix(), patch.as_posix())
        code = self.source.read_text(encoding="utf-8")
        # Only test-local filesystem boundaries change; parser/control flow and
        # all functions come from the actual patched upstream source.
        self.private = self.base / "etc/ssrplus/nftables"
        self.legacy = self.base / "usr/share/nftables.d/ruleset-post"
        self.backup = self.base / "etc/ssrplus/ssrplus-persist"
        for path in (self.private, self.legacy, self.backup, self.base / "var/run",
                     self.base / "var/lock", self.base / "tmp", self.base / "proc"):
            path.mkdir(parents=True)
        prefixes = ("/etc/ssrplus/", "/usr/share/nftables.d/", "/var/run/", "/var/lock/", "/tmp/")
        # One pass is important on Linux: inserted /tmp/test-root paths must
        # not themselves be rewritten by the final /tmp/ substitution.
        code = re.sub("|".join(re.escape(prefix) for prefix in prefixes),
                      lambda match: self.base.as_posix() + match.group(), code)
        code = code.replace('SSRP_RULES_SCRIPT="/usr/bin/ssr-rules"',
                            'SSRP_RULES_SCRIPT="$TEST_ROOT/ssr-rules"')
        code = code.replace('SSRP_PROC_ROOT="/proc"', 'SSRP_PROC_ROOT="$TEST_ROOT/proc"')
        self.command = self.base / "ssr-rules"
        self.command.write_text(code, encoding="utf-8", newline="\n")
        self.command.chmod(0o755)
        self.definitions = self.base / "definitions.sh"
        self.definitions.write_text(code[:code.index('while getopts ')],
                                    encoding="utf-8", newline="\n")
        init = self.base / "etc/init.d/shadowsocksr"
        init.parent.mkdir(parents=True)
        init.write_text(r'''
check_run_environment() { USE_TABLES=nftables; }
echolog() { :; }
uci() { printf '%s/include.sh\n' "$TEST_ROOT"; }
logger() { :; }
flock() { printf '%s\n' "$*" >> "$TEST_ROOT/lock.log"; }
nft() {
    printf '%s\n' "$*" >> "$TEST_ROOT/nft.log"
    case "$*" in
        'list tables')
            [ -e "$TEST_ROOT/deleted-inet" ] || printf 'table inet ss_spec\n'
            [ -e "$TEST_ROOT/deleted-mangle" ] || printf 'table ip ss_spec_mangle\n'
            return 0 ;;
        'list table inet ss_spec') [ ! -e "$TEST_ROOT/deleted-inet" ] && cat "$TEST_ROOT/inet.nft" ;;
        'list table ip ss_spec_mangle') [ ! -e "$TEST_ROOT/deleted-mangle" ] && cat "$TEST_ROOT/mangle.nft" ;;
        'delete table inet ss_spec') [ ! -e "$TEST_ROOT/fail-delete" ] && touch "$TEST_ROOT/deleted-inet" ;;
        'delete table ip ss_spec_mangle') [ ! -e "$TEST_ROOT/fail-delete" ] && touch "$TEST_ROOT/deleted-mangle" ;;
        'flush chain '*|'delete chain '*|'flush set '*|'delete set '*) return 0 ;;
        '-c -f '*) [ ! -e "$TEST_ROOT/reject-check" ] ;;
        '-f '*) cat "$2" > "$TEST_ROOT/applied.nft"; rm -f "$TEST_ROOT/deleted-inet" "$TEST_ROOT/deleted-mangle" ;;
        *) return 1 ;;
    esac
}
ip() {
    printf '%s\n' "$*" >> "$TEST_ROOT/ip.log"
    case "$*" in 'rule show'|'route show table 999') return 0 ;; esac
    return 0
}
''', encoding="utf-8", newline="\n")
        (self.base / "inet.nft").write_text(INET, encoding="utf-8", newline="\n")
        (self.base / "mangle.nft").write_text(MANGLE, encoding="utf-8", newline="\n")
        self.snapshot = self.private / "99-shadowsocksr.nft"
        self.snapshot.write_text(INET + MANGLE, encoding="utf-8", newline="\n")
        # Also seed the original location so the unpatched restore really
        # exercises its destructive path rather than stopping at "not found".
        (self.legacy / "99-shadowsocksr.nft").write_text(
            INET + MANGLE, encoding="utf-8", newline="\n")
        self.pidfile = self.base / "var/run/ssr-rules-daemon.pid"
        self.active = self.base / "var/run/ssr-rules-auto-restore.enabled"

    def shell(self, code, *args, check=True):
        result = subprocess.run([self.bash, "--noprofile", "--norc", "-c", code,
                                 "test", *args], env=self.env, text=True, encoding="utf-8",
                                capture_output=True, timeout=30)
        if check and result.returncode:
            self.fail(f"shell exited {result.returncode}: {result.stdout}\n{result.stderr}")
        return result

    def cli(self, *args):
        return self.shell('IPKG_INSTROOT="$TEST_ROOT" bash "$TEST_ROOT/ssr-rules" "$@"',
                          *args, check=False)

    def functions(self, code):
        return self.shell('export IPKG_INSTROOT="$TEST_ROOT"; source "$TEST_ROOT/definitions.sh"\n' + code,
                          check=False)

    def write_process(self, pid=4242, start=12345, command=None):
        proc = self.base / "proc" / str(pid)
        proc.mkdir(exist_ok=True)
        # Linux stat field 22 is starttime; comm may contain spaces/parentheses.
        (proc / "stat").write_text(f"{pid} (ssr rules (worker)) S " +
                                   " ".join(["0"] * 18 + [str(start), "0", "0"]) + "\n")
        (proc / "cmdline").write_bytes(command or (
            b"/bin/sh\0" + self.command.as_posix().encode() + b"\0--persistence-daemon\0"))
        return proc

    def test_stale_or_reused_pid_never_receives_a_signal(self):
        self.write_process(start=999)
        self.pidfile.write_text("4242 12345\n", newline="\n")
        result = self.functions(r'''
kill() { printf '%s\n' "$*" >> "$TEST_ROOT/signals"; return 0; }
stop_auto_update_daemon
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.base / "signals").exists(), "reused PID received a signal")
        self.assertFalse(self.pidfile.exists())

    def test_matching_starttime_with_an_unrelated_command_is_not_killed(self):
        self.write_process(command=b"/usr/sbin/dnsmasq\0--keep-in-foreground\0")
        self.pidfile.write_text("4242 12345\n", newline="\n")
        result = self.functions(r'''
kill() { printf '%s\n' "$*" >> "$TEST_ROOT/signals"; return 0; }
stop_auto_update_daemon
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.base / "signals").exists(), "unrelated process received a signal")

    def test_legacy_single_pid_and_malformed_metadata_never_receive_a_signal(self):
        self.write_process()
        for record in ("4242\n", "4242 12345 extra\n", "0 12345\n", "1 12345\n",
                       "-42 12345\n", "4242 nope\n"):
            with self.subTest(record=record):
                self.pidfile.write_text(record, newline="\n")
                result = self.functions(r'''
kill() { printf '%s\n' "$*" >> "$TEST_ROOT/signals"; return 0; }
stop_auto_update_daemon
''')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse((self.base / "signals").exists())

    def test_failed_pidfile_publication_does_not_leave_an_untracked_daemon(self):
        result = self.functions(r'''
SSRP_PROC_ROOT=/proc
mktemp() { return 1; }
trap 'for child in $(jobs -p); do kill -TERM "$child" 2>/dev/null; done' EXIT
start_auto_update_daemon && exit 11
[ -z "$(jobs -pr)" ] || exit 12
[ ! -e "$SSRP_DAEMON_PID_FILE" ]
''')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_start_records_the_real_child_and_stop_waits_for_that_process(self):
        result = self.functions(r'''
SSRP_PROC_ROOT=/proc
trap 'for child in $(jobs -p); do kill -TERM "$child" 2>/dev/null; done' EXIT
start_auto_update_daemon || exit 11
read -r daemon_pid started < "$SSRP_DAEMON_PID_FILE"
[ "$daemon_pid" != "$$" ] || exit 12
daemon_pid_matches "$daemon_pid" "$started" || exit 13
printf '%s\n' "$daemon_pid" > "$TEST_ROOT/real-daemon"
stop_auto_update_daemon || exit 14
daemon_pid_matches "$daemon_pid" "$started" && exit 15
[ ! -f "$SSRP_DAEMON_PID_FILE" ]
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.base / "real-daemon").read_text().strip().isdigit())

    def test_valid_daemon_is_terminated_and_polled_until_its_identity_disappears(self):
        self.write_process()
        self.pidfile.write_text("4242 12345\n", newline="\n")
        result = self.functions(r'''
kill() {
    printf '%s\n' "$*" >> "$TEST_ROOT/signals"
    case "$*" in '-TERM 4242') rm -rf "$TEST_ROOT/proc/4242" ;; esac
    return 0
}
stop_auto_update_daemon
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.base / "signals").read_text().splitlines(), ["-TERM 4242"])
        self.assertFalse(self.pidfile.exists())

    def test_stop_timeout_preserves_metadata_and_prevents_a_duplicate_start(self):
        self.write_process()
        self.pidfile.write_text("4242 12345\n", newline="\n")
        result = self.functions(r'''
kill() { printf '%s\n' "$*" >> "$TEST_ROOT/signals"; return 0; }
sleep() { :; }
start_auto_update_daemon && exit 11
[ -f "$SSRP_DAEMON_PID_FILE" ] || exit 12
[ -z "$(jobs -pr)" ] || exit 13
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.base / "signals").read_text().splitlines(), ["-TERM 4242"])

    def test_restore_parser_failure_preserves_live_rules_and_basic_nat(self):
        (self.base / "reject-check").touch()
        result = self.cli("-R")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.base / "applied.nft").exists(),
                         "invalid snapshot reached nft's mutating invocation")
        log = (self.base / "nft.log").read_text()
        self.assertNotIn("flush chain", log)
        self.assertNotIn("delete table", log)

    def test_restore_rejects_commands_outside_ssr_tables_before_parser(self):
        for text in ("flush ruleset\n" + INET, INET + "table inet fw4 { }\n",
                     INET + "include \"/etc/nftables.conf\"\n", INET + "}\n",
                     'table inet ss_spec {\n include "/etc/nftables.conf"\n}\n',
                     INET.rstrip()[:-1] + "} flush ruleset\n"):
            with self.subTest(text=text):
                self.snapshot.write_text(text, encoding="utf-8", newline="\n")
                for name in ("nft.log", "applied.nft"):
                    (self.base / name).unlink(missing_ok=True)
                result = self.cli("-R")
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.base / "applied.nft").exists())
                self.assertFalse((self.base / "nft.log").exists(),
                                 "out-of-scope snapshot was passed to nft")

    def test_restore_replaces_only_ssr_tables_in_one_checked_transaction(self):
        result = self.cli("-R")
        self.assertEqual(result.returncode, 0, result.stderr)
        transaction = (self.base / "applied.nft").read_text()
        self.assertIn("delete table inet ss_spec\n", transaction)
        self.assertIn("delete table ip ss_spec_mangle\n", transaction)
        self.assertIn(INET + MANGLE, transaction)
        self.assertNotIn("flush ruleset", transaction)
        self.assertNotIn("fw4", transaction)
        log = (self.base / "nft.log").read_text().splitlines()
        self.assertEqual(sum(line.startswith("-c -f ") for line in log), 1)
        self.assertEqual(sum(line.startswith("-f ") for line in log), 1)
        self.assertLess(next(i for i, line in enumerate(log) if line.startswith("-c -f ")),
                        next(i for i, line in enumerate(log) if line.startswith("-f ")))
        routes = (self.base / "ip.log").read_text()
        self.assertIn("rule add fwmark 0x53535250 table 999", routes)
        self.assertIn("route add local 0.0.0.0/0 dev lo table 999", routes)

    def test_fw4_hook_tolerates_rejected_snapshot_and_keeps_base_firewall(self):
        self.active.touch()
        result = self.functions('gen_include_nft\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        hook = self.base / "include.sh"
        (self.base / "reject-check").touch()
        result = self.shell('IPKG_INSTROOT="$TEST_ROOT" bash "$TEST_ROOT/include.sh"', check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.base / "applied.nft").exists())
        self.assertNotIn("nftables.d/ruleset-post", hook.read_text())

    def test_dispatched_hook_cannot_restore_after_stop_but_manual_restore_can(self):
        self.active.touch()
        result = self.functions("gen_include_nft")
        self.assertEqual(result.returncode, 0, result.stderr)
        queued_hook = self.base / "queued-hook.sh"
        shutil.copyfile(self.base / "include.sh", queued_hook)
        result = self.cli("-f")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.active.exists(), "stop did not disable automatic restore")
        result = self.shell('IPKG_INSTROOT="$TEST_ROOT" bash "$TEST_ROOT/queued-hook.sh"', check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.base / "applied.nft").exists(), "queued hook recreated SSR after stop")
        result = self.cli("-R")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.base / "applied.nft").exists(), "explicit manual restore was disabled")

    def test_failed_flush_disables_auto_restore_and_reports_remaining_tables(self):
        self.active.touch()
        (self.base / "fail-delete").touch()
        result = self.cli("-f")
        self.assertNotEqual(result.returncode, 0, "-f hid surviving SSR tables")
        self.assertFalse(self.active.exists())

    def test_gated_restore_rechecks_marker_after_waiting_for_the_lock(self):
        self.active.touch()
        init = self.base / "etc/init.d/shadowsocksr"
        init.write_text(init.read_text().replace(
            'flock() { printf',
            'flock() { rm -f "$TEST_ROOT/var/run/ssr-rules-auto-restore.enabled"; printf'),
            encoding="utf-8", newline="\n")
        result = self.cli("--firewall-restore")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.base / "applied.nft").exists(), "restore decided before lock acquisition")

    def test_cleanup_reports_a_failed_persistence_removal(self):
        result = self.functions('rm() { return 1; }; cleanup_persistence_files\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.snapshot.exists())

    def prepare_full_setup(self):
        operations = r'''
ipset_r() {
    printf 'rebuild\n' >> "$TEST_ROOT/rebuild.log"
    [ ! -e "$TEST_ROOT/fail-rebuild" ] || return 1
    rm -f "$TEST_ROOT/deleted-inet" "$TEST_ROOT/deleted-mangle"
    [ ! -f "$TEST_ROOT/next-inet.nft" ] || cp "$TEST_ROOT/next-inet.nft" "$TEST_ROOT/inet.nft"
}
fw_rule() { :; }
ac_rule() { :; }
tp_rule() { :; }
'''
        self.command.write_text(self.command.read_text(encoding="utf-8").replace(
            '# Main process\n', operations + '\n# Main process\n', 1),
            encoding="utf-8", newline="\n")
        self.ignore = self.base / "ignore.txt"
        self.shunt = self.base / "shunt.txt"
        self.ignore.write_text("192.0.2.1\n", newline="\n")
        self.shunt.write_text("198.51.100.9\n", newline="\n")
        self.setup_args = ("-s", "198.51.100.1", "-l", "1234", "-r",
                           "-i", self.ignore.as_posix(), "-I", self.shunt.as_posix())

    def test_changed_canonical_list_contents_rebuild_instead_of_restoring_old_sets(self):
        self.prepare_full_setup()
        for iteration, changed in enumerate((None, self.ignore, self.shunt), 1):
            if changed:
                changed.write_text(f"203.0.113.{iteration}\n", newline="\n")
                (self.base / "next-inet.nft").write_text(
                    INET.replace("192.0.2.1", f"203.0.113.{iteration}"), newline="\n")
                (self.base / "applied.nft").unlink(missing_ok=True)
            result = self.cli(*self.setup_args)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((self.base / "rebuild.log").read_text().splitlines(), ["rebuild"] * iteration)
            self.assertTrue(self.active.exists(), "successful setup did not enable automatic restore")
            if changed:
                self.assertFalse((self.base / "applied.nft").exists(), "changed list restored a stale snapshot")
                self.assertIn(f"203.0.113.{iteration}", self.snapshot.read_text())
            result = self.cli(*self.setup_args)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((self.base / "rebuild.log").read_text().splitlines(), ["rebuild"] * iteration,
                             "unchanged list caused an unnecessary rebuild")

    def test_failed_rebuild_keeps_old_fingerprint_so_retry_cannot_restore_stale_sets(self):
        self.prepare_full_setup()
        self.assertEqual(self.cli(*self.setup_args).returncode, 0)
        self.ignore.write_text("203.0.113.20\n", newline="\n")
        (self.base / "next-inet.nft").write_text(INET.replace("192.0.2.1", "203.0.113.20"), newline="\n")
        (self.base / "fail-rebuild").touch()
        result = self.cli(*self.setup_args)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.active.exists(), "failed setup left automatic restore enabled")
        (self.base / "fail-rebuild").unlink()
        (self.base / "applied.nft").unlink(missing_ok=True)
        result = self.cli(*self.setup_args)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len((self.base / "rebuild.log").read_text().splitlines()), 3)
        self.assertFalse((self.base / "applied.nft").exists(), "retry restored stale rules after failed rebuild")
        self.assertIn("203.0.113.20", self.snapshot.read_text())

    def test_hook_publication_failure_preserves_the_previous_complete_hook(self):
        hook = self.base / "include.sh"
        previous = b"#!/bin/sh\n# previous complete hook\nexit 0\n"
        hook.write_bytes(previous)
        result = self.functions('mv() { return 1; }; gen_include_nft\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(hook.read_bytes(), previous)
        self.assertEqual(list(self.base.glob("include.sh.*")), [])

    def test_legacy_global_include_is_removed_without_importing_bad_text(self):
        legacy_file = self.legacy / "99-shadowsocksr.nft"
        legacy_file.write_text("BROKEN PUBLIC INCLUDE\n")
        result = self.cli("-P")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(legacy_file.exists(), "fw4 can still auto-load the legacy snapshot")
        self.assertNotIn("BROKEN", self.snapshot.read_text())

    def test_backup_migration_is_private_and_validated_before_restore(self):
        self.snapshot.unlink()
        (self.backup / "99-shadowsocksr.save").write_text(INET + MANGLE, encoding="utf-8", newline="\n")
        result = self.cli("-R")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.snapshot.exists())
        self.assertFalse((self.legacy / "99-shadowsocksr.nft").exists())

    def test_mutating_cli_holds_one_separate_lock_for_export_and_daemon_stop(self):
        for args in (("-P",), ("-K",), ("-R",), ("-X",)):
            with self.subTest(args=args):
                (self.base / "lock.log").unlink(missing_ok=True)
                if args == ("-R",):
                    self.snapshot.write_text(INET, encoding="utf-8", newline="\n")
                result = self.cli(*args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual((self.base / "lock.log").read_text().splitlines(), ["-w 30 -x 8"])

    def test_lock_failure_prevents_export_and_migration(self):
        init = self.base / "etc/init.d/shadowsocksr"
        init.write_text(init.read_text().replace(
            'flock() { printf', 'flock() { return 1; printf'), encoding="utf-8", newline="\n")
        previous = self.snapshot.read_bytes()
        result = self.cli("-P")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.snapshot.read_bytes(), previous)
        self.assertTrue((self.legacy / "99-shadowsocksr.nft").exists())
        self.assertFalse((self.base / "nft.log").exists())

    def test_full_setup_reports_daemon_start_failure(self):
        # Kernel rule installation is outside this result-propagation case;
        # its nft export and complete CLI option/control flow remain real.
        operations = r'''
flush_r() { :; }
ipset_r() { :; }
fw_rule() { :; }
ac_rule() { :; }
tp_rule() { :; }
gen_include() { :; }
start_auto_update_daemon() { return 1; }
'''
        self.command.write_text(self.command.read_text(encoding="utf-8").replace(
            '# Main process\n', operations + '\n# Main process\n', 1),
            encoding="utf-8", newline="\n")
        result = self.cli("-s", "198.51.100.1", "-l", "1234", "-A")
        self.assertIn("table inet ss_spec", self.snapshot.read_text())
        self.assertNotEqual(result.returncode, 0, "full setup hid daemon startup failure")

    def test_patch_dependency_and_reverse_check(self):
        if not PATCHES[1].exists() or os.environ.get("SSR_LIFECYCLE_UNPATCHED"):
            self.skipTest("new lifecycle patch is intentionally absent")
        self.shell('git -C "$1" apply --reverse --check "$2"',
                   self.base.as_posix(), PATCHES[1].as_posix())
        self.shell('bash -n "$1"', self.source.as_posix())


if __name__ == "__main__":
    unittest.main()
