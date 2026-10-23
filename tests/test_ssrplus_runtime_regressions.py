#!/usr/bin/env python3
# Historical 190-r12 regression only; production v198.2 coverage is test_ssrplus_v198.py.
"""Run the SSR compatibility runtime in a temporary local filesystem.

No router is contacted. Bash executes the production helper; the portable cases
replace only unavailable OS programs (flock failure / dnsmasq validation). Real
flock, process-death and installed-dnsmasq cases are explicitly skipped when the
host does not provide them. They must run on Linux before firmware acceptance.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "tests/fixtures/ssrplus-legacy/wrt_core/compat/ssrplus/runtime.sh"
BASH = os.environ.get("BASH") or shutil.which("bash")
if os.name == "nt" and not BASH:
    BASH = "C:/Program Files/Git/bin/bash.exe"

# A deliberately small boundary substitute, not a dnsmasq implementation. This
# verifies that publication consults the external validator and honors failure.
PORTABLE_PROGRAMS = r'''
flock() { return 0; }
dnsmasq() {
    [ "$#" = 2 ] && [ "$1" = --test ] || return 65
    case "$2" in --conf-file=*) ;; *) return 66 ;; esac
    validation_file=${2#--conf-file=}
    printf '%s\n' "$validation_file" >> "$TEST_ROOT/validated"
    [ -f "$validation_file" ] || return 67
    ! grep -Eq '^[[:space:]]*ipset=' "$validation_file" || return 68
}
'''


def read_shared_text(path):
    """Allow rename while reading, as a Linux dnsmasq reader does.

    Native Python opens on Windows omit FILE_SHARE_DELETE and can make Git Bash
    mv fail with EBUSY. Explicit sharing preserves the intended atomic-rename
    experiment without replacing publication or relaxing content assertions.
    """
    if os.name != "nt":
        return path.read_text(encoding="utf-8")
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel.CreateFileW
    create_file.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                            ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                            wintypes.HANDLE)
    create_file.restype = wintypes.HANDLE
    handle = create_file(str(path), 0x80000000, 0x1 | 0x2 | 0x4,
                         None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY)
    with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
        return stream.read()


@unittest.skipUnless(BASH, "Bash is required to execute the shell runtime")
class RuntimeRegressions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ssrplus-regressions-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.conf_dir = self.base / "dnsmasq.d"
        self.active = self.base / "dnsmasq-ssrplus.d"
        self.published = self.conf_dir / "dnsmasq-ssrplus.conf"
        self.active.mkdir()
        self.conf_dir.mkdir()
        self.old = "server=/old.example/192.0.2.1\n"
        self.published.write_text(self.old, encoding="utf-8", newline="\n")
        self.env = os.environ.copy()
        self.env.update(MSYS_NO_PATHCONV="1", TEST_ROOT=self.base.as_posix(),
                        SSRP_RUNTIME=RUNTIME.as_posix())
        self.preamble = r'''
            . "$SSRP_RUNTIME" || exit
            LOCK_FILE="$TEST_ROOT/lifecycle.lock"
            DNSMASQ_CONF_DIR="$TEST_ROOT/dnsmasq.d"
            TMP_DNSMASQ_PATH="$TEST_ROOT/dnsmasq-ssrplus.d"
        '''

    def shell(self, body, *, programs=PORTABLE_PROGRAMS, check=True, timeout=60):
        result = subprocess.run(
            [BASH, "--noprofile", "--norc", "-c", self.preamble + programs + body],
            env=self.env, capture_output=True, text=True, timeout=timeout,
        )
        if check and result.returncode:
            self.fail(f"shell exited {result.returncode}: {result.stdout}\n{result.stderr}")
        return result

    def assert_old_generation(self):
        self.assertEqual(self.published.read_text(encoding="utf-8"), self.old)

    def assert_no_stage(self):
        self.assertEqual(list(self.conf_dir.glob(".ssrplus-*")), [],
                         "the transaction leaked staging or include files")

    def published_content(self):
        return read_shared_text(self.published)

    def patched_sources(self):
        package = self.base / "package"
        init = package / "root/etc/init.d/shadowsocksr"
        generator = package / "root/usr/share/shadowsocksr/gfw2ipset.sh"
        init.parent.mkdir(parents=True)
        generator.parent.mkdir(parents=True)
        fixture = ROOT / "tests/fixtures/ssrplus/2abdc9aa"
        shutil.copyfile(fixture / "shadowsocksr.init", init)
        shutil.copyfile(fixture / "gfw2ipset.sh", generator)
        shutil.copyfile(fixture / "update.lua", generator.parent / "update.lua")
        for arguments in (("init", "-q"),
                          ("apply", str(ROOT / "tests/fixtures/ssrplus-legacy/wrt_core/patches/ssrplus-startup-lock.patch")),
                          ("apply", str(ROOT / "tests/fixtures/ssrplus-legacy/wrt_core/patches/ssrplus-dns-transaction.patch"))):
            result = subprocess.run(["git", "-C", str(package), *arguments],
                                    env=self.env, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0,
                             f"fixture patch setup failed: {result.stderr}")
        # Relocate only fixed system paths; function bodies execute unchanged.
        init.write_text(init.read_text(encoding="utf-8").replace(
            "${IPKG_INSTROOT:-}/usr/share/shadowsocksr/ssrp-runtime.sh", RUNTIME.as_posix()),
            encoding="utf-8", newline="\n")
        self.env["SSR_INIT"] = init.as_posix()
        return init, generator

    def generator_fixture(self, run_mode):
        _, generator = self.patched_sources()
        rules = self.base / "rules"
        rules.mkdir()
        for name, domain in (("gfw_base.conf", "base.example"),
                             ("gfw_list.conf", "list.example"),
                             ("oversea_list.conf", "oversea.example")):
            (rules / name).write_text(
                f"server=/{domain}/127.0.0.1#5335\nipset=/{domain}/gfwlist\n",
                encoding="utf-8", newline="\n")
        for name in ("white.list", "black.list", "deny.list", "netflix.list"):
            (rules / name).write_text("", encoding="utf-8")
        stub = self.base / "generator-init-boundary.sh"
        stub.write_text(r'''
USE_TABLES=nftables
dns_port=5335
DNSMASQ_CONF_DIR="$TEST_ROOT/dnsmasq.d"
check_run_environment() { :; }
echolog() { :; }
uci_get_by_type() {
    case "$2" in
        run_mode) printf '%s\n' "$RUN_MODE" ;;
        netflix_enable|adblock) echo 0 ;;
        global_server) echo nil ;;
        *) printf '%s\n' "$3" ;;
    esac
}
''', encoding="utf-8", newline="\n")
        text = generator.read_text(encoding="utf-8")
        text = text.replace(". $IPKG_INSTROOT/etc/init.d/shadowsocksr",
                            f'. "{stub.as_posix()}"')
        text = text.replace("/etc/ssrplus/", rules.as_posix() + "/")
        generator.write_text(text, encoding="utf-8", newline="\n")
        self.env.update(SSR_GENERATOR=generator.as_posix(), RUN_MODE=run_mode)
        return rules

    def test_failed_lock_never_executes_critical_body(self):
        result = self.shell(r'''
            flock() { return 1; }
            critical() { printf 'entered\n' > "$TEST_ROOT/entered"; }
            ssrp_run_locked critical
        ''', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.base / "entered").exists(),
                         "critical work executed after lock acquisition failed")

    def test_critical_failure_propagates_and_lock_inode_is_kept(self):
        result = self.shell(r'''
            critical() { return 42; }
            ssrp_run_locked critical
        ''', check=False)
        self.assertEqual(result.returncode, 42)
        self.assertTrue((self.base / "lifecycle.lock").exists(),
                        "unlinking a lock lets waiters lock different inodes")

    def test_critical_body_itself_retains_lock_descriptor(self):
        # A separate guardian holding the lock can die while its worker keeps
        # changing the firewall/DNS. The process doing that work must own FD9;
        # only daemon launch boundaries close it (tested separately below).
        result = self.shell(r'''
            critical() { ( : >&9 ) 2>/dev/null; }
            ssrp_run_locked critical
        ''', check=False)
        self.assertEqual(result.returncode, 0,
                         "critical work was detached from the lock owner")

    def test_second_start_stops_existing_processes_before_replacement(self):
        self.patched_sources()
        self.shell(r'''
            . "$SSR_INIT" || exit
            LOCK_FILE="$TEST_ROOT/lifecycle.lock"
            TMP_PATH="$TEST_ROOT/service"
            PS=test_ps
            test_ps() {
                [ -f "$TEST_ROOT/running" ] && printf '123 %s/client\n' "$TMP_PATH"
            }
            ssrp_start() { touch "$TEST_ROOT/running"; echo start >> "$TEST_ROOT/order"; }
            ssrp_stop() { rm -f "$TEST_ROOT/running"; echo stop >> "$TEST_ROOT/order"; }
            start || exit
            start
        ''')
        self.assertEqual((self.base / "order").read_text().splitlines(),
                         ["start", "stop", "start"],
                         "a repeated start launched a second process group")

    def test_restart_does_not_start_after_stop_failure(self):
        result = self.shell(r'''
            ssrp_stop() { return 23; }
            ssrp_start() { touch "$TEST_ROOT/started"; }
            ssrp_run_locked ssrp_restart_locked
        ''', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.base / "started").exists())

    def test_patched_init_background_launcher_does_not_inherit_lock_fd(self):
        self.patched_sources()
        self.shell(r'''
            . "$SSR_INIT" || exit
            LOCK_FILE="$TEST_ROOT/lifecycle.lock"
            TMP_BIN_PATH="$TEST_ROOT/bin"
            mkdir -p "$TMP_BIN_PATH" || exit
            cat > "$TMP_BIN_PATH/daemon" <<'DAEMON'
#!/bin/sh
if ( : >&9 ) 2>/dev/null; then
    echo leaked > "$TEST_ROOT/daemon-fd"
else
    echo closed > "$TEST_ROOT/daemon-fd"
fi
DAEMON
            chmod +x "$TMP_BIN_PATH/daemon" || exit
            critical() {
                ln_start_bin "$TMP_BIN_PATH/daemon" test-daemon
                for attempt in $(seq 1 100); do
                    [ -f "$TEST_ROOT/daemon-fd" ] && return 0
                    sleep 0.01
                done
                return 1
            }
            ssrp_run_locked critical
        ''')
        self.assertEqual((self.base / "daemon-fd").read_text().strip(), "closed",
                         "a spawned service inherited the lifecycle lock descriptor")

    def test_patched_init_public_restart_is_one_critical_operation(self):
        self.patched_sources()
        self.shell(r'''
            . "$SSR_INIT" || exit
            LOCK_FILE="$TEST_ROOT/lifecycle.lock"
            flock() { echo lock >> "$TEST_ROOT/order"; }
            ssrp_stop() { echo stop >> "$TEST_ROOT/order"; }
            ssrp_start() { echo start >> "$TEST_ROOT/order"; }
            restart
        ''')
        self.assertEqual((self.base / "order").read_text().splitlines(),
                         ["lock", "stop", "start"],
                         "restart released and reacquired its lock between stop and start")

    def test_actual_stop_succeeds_when_short_log_needs_no_truncation(self):
        init, _ = self.patched_sources()
        init.write_text(init.read_text(encoding="utf-8").replace(
            "/usr/bin/ssr-rules", "test_ssr_rules"), encoding="utf-8", newline="\n")
        self.shell(r'''
            . "$SSR_INIT" || exit
            LOCK_FILE="$TEST_ROOT/lifecycle.lock"
            DNSMASQ_CONF_DIR="$TEST_ROOT/dnsmasq.d"
            TMP_DNSMASQ_PATH="$TEST_ROOT/dnsmasq-ssrplus.d"
            TMP_PATH="$TEST_ROOT/service"
            CRON_FILE="$TEST_ROOT/crontab"
            LOG_FILE="$TEST_ROOT/service.log"
            printf 'one healthy log line\n' > "$LOG_FILE"
            switch_server=test
            PS=test_ps
            test_ps() { :; }
            test_ssr_rules() { :; }
            check_run_environment() { USE_TABLES=none; HAS_IPSET=0; }
            uci() { :; }
            xargs() { cat >/dev/null; }
            killall() { :; }
            rm() { :; }
            sleep() { :; }
            crontab() { :; }
            ssrp_dnsmasq() { :; }
            # The real del_cron and clean_log remain in the call chain. A
            # short log makes clean_log's terminal test return 1 harmlessly.
            stop || exit
            ssrp_start() { echo activated > "$TEST_ROOT/restarted"; }
            restart
        ''')
        self.assertEqual((self.base / "service.log").read_text(),
                         "one healthy log line\n")
        self.assertEqual((self.base / "restarted").read_text().strip(), "activated")

    def test_stage_is_hidden_and_abort_preserves_published_generation(self):
        self.shell(r'''
            ssrp_dns_begin || exit
            printf '%s\n' "$SSRP_DNS_STAGE" > "$TEST_ROOT/stage-name"
            printf 'ipset=/raw.example/gfwlist\n' > "$TMP_DNSMASQ_PATH/raw.conf"
            # Only non-hidden files in the dnsmasq include directory are live.
            find "$DNSMASQ_CONF_DIR" -maxdepth 1 -type f ! -name '.*' -print > "$TEST_ROOT/visible"
            ssrp_dns_abort
            [ "$TMP_DNSMASQ_PATH" = "$TEST_ROOT/dnsmasq-ssrplus.d" ]
        ''')
        stage = Path((self.base / "stage-name").read_text().strip())
        self.assertTrue(stage.name.startswith(".ssrplus-"))
        self.assertFalse(stage.exists())
        self.assertEqual((self.base / "visible").read_text().splitlines(),
                         [self.published.as_posix()])
        self.assert_old_generation()
        self.assert_no_stage()

    def test_failed_generation_aborts_stage_under_lifecycle_lock(self):
        result = self.shell(r'''
            critical() {
                ssrp_dns_begin || return
                printf 'ipset=/incomplete.example/gfwlist\n' > "$TMP_DNSMASQ_PATH/gfw.conf"
                return 27
            }
            ssrp_run_locked critical
        ''', check=False)
        self.assertEqual(result.returncode, 27)
        self.assert_old_generation()
        self.assert_no_stage()

    def test_no_ipset_validator_failure_keeps_previous_generation(self):
        result = self.shell(r'''
            critical() {
                ssrp_dns_begin || return
                printf 'ipset=/unsupported.example/gfwlist\n' > "$TMP_DNSMASQ_PATH/gfw.conf"
                ssrp_dns_publish
            }
            ssrp_run_locked critical
        ''', check=False)
        self.assertNotEqual(result.returncode, 0,
                            "unsupported generated directives were published")
        self.assertTrue((self.base / "validated").exists(),
                        "publication skipped the external dnsmasq validator")
        self.assert_old_generation()
        self.assert_no_stage()

    def test_real_generator_converts_gfw_ipset_before_publication(self):
        self.generator_fixture("gfw")
        self.shell(r'''
            critical() {
                ssrp_dns_begin || return
                SSRP_DNS_STAGE="$TMP_DNSMASQ_PATH" "$BASH" "$SSR_GENERATOR" || return
                ssrp_dns_publish
            }
            ssrp_run_locked critical
        ''')
        content = self.published_content()
        self.assertNotIn("ipset=", content)
        self.assertIn("nftset=/base.example/inet#ss_spec#gfwlist\n", content)
        self.assertIn("nftset=/list.example/inet#ss_spec#gfwlist\n", content)
        self.assert_no_stage()

    def test_real_generator_removes_oversea_ipset_for_no_ipset_dnsmasq(self):
        self.generator_fixture("oversea")
        self.shell(r'''
            critical() {
                ssrp_dns_begin || return
                SSRP_DNS_STAGE="$TMP_DNSMASQ_PATH" "$BASH" "$SSR_GENERATOR" || return
                ssrp_dns_publish
            }
            ssrp_run_locked critical
        ''')
        content = self.published_content()
        self.assertNotIn("ipset=", content)
        self.assertIn("server=/oversea.example/127.0.0.1#5335\n", content)
        self.assert_no_stage()

    def test_real_generator_copy_failure_cannot_publish_partial_rules(self):
        rules = self.generator_fixture("gfw")
        (rules / "gfw_base.conf").unlink()
        result = self.shell(r'''
            critical() {
                ssrp_dns_begin || return
                SSRP_DNS_STAGE="$TMP_DNSMASQ_PATH" "$BASH" "$SSR_GENERATOR" || return
                ssrp_dns_publish
            }
            ssrp_run_locked critical
        ''', check=False)
        self.assertNotEqual(result.returncode, 0,
                            "generator ignored a failed source copy")
        self.assertFalse((self.base / "validated").exists(),
                         "incomplete generation reached the publication validator")
        self.assert_old_generation()
        self.assert_no_stage()

    def test_validated_fragments_publish_as_one_complete_bundle(self):
        self.shell(r'''
            critical() {
                ssrp_dns_begin || return
                printf 'server=/one.example/127.0.0.1#5335\n' > "$TMP_DNSMASQ_PATH/one.conf"
                printf 'nftset=/one.example/inet#ss_spec#gfwlist\n' > "$TMP_DNSMASQ_PATH/two.conf"
                ssrp_dns_publish
            }
            ssrp_run_locked critical
        ''')
        self.assertEqual(self.published_content(),
                         "server=/one.example/127.0.0.1#5335\n\n"
                         "nftset=/one.example/inet#ss_spec#gfwlist\n\n")
        validation = (self.base / "validated").read_text().splitlines()
        self.assertEqual(len(validation), 1)
        self.assertTrue(Path(validation[0]).name.startswith("."))
        self.assert_no_stage()

    def test_copy_failure_keeps_previous_generation(self):
        result = self.shell(r'''
            cp() { return 28; }
            critical() {
                ssrp_dns_begin || return
                printf 'server=/new.example/192.0.2.2\n' > "$TMP_DNSMASQ_PATH/new.conf"
                ssrp_dns_publish
            }
            ssrp_run_locked critical
        ''', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assert_old_generation()
        self.assert_no_stage()

    def test_failed_atomic_publish_keeps_previous_generation(self):
        result = self.shell(r'''
            mv() {
                case "$*" in *dnsmasq-ssrplus.conf) return 29 ;; esac
                command mv "$@"
            }
            critical() {
                ssrp_dns_begin || return
                printf 'server=/new.example/192.0.2.2\n' > "$TMP_DNSMASQ_PATH/new.conf"
                ssrp_dns_publish
            }
            ssrp_run_locked critical
        ''', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assert_old_generation()
        self.assert_no_stage()

    def test_reader_never_sees_raw_or_partial_generated_rules(self):
        expected = {self.old}
        for index in range(15):
            expected.add(f"server=/new-{index}.example/192.0.2.2\n" * 200 + "\n")
        observed, failures = set(), []
        read_count = 0
        stop = threading.Event()

        def reader():
            nonlocal read_count
            inaccessible_since = None
            while not stop.is_set():
                try:
                    value = self.published_content()
                    if value not in expected:
                        failures.append(f"raw or partial generation: {value[:100]!r}")
                        return
                    observed.add(value)
                    read_count += 1
                    inaccessible_since = None
                except OSError as exc:
                    # Git Bash's Windows rename temporarily denies a native
                    # Python open. Linux readers must never get this error.
                    # Retry only that host-specific condition, for <=100 ms.
                    if os.name == "nt" and isinstance(exc, PermissionError):
                        inaccessible_since = inaccessible_since or time.monotonic()
                        if time.monotonic() - inaccessible_since < 0.1:
                            time.sleep(0.001)
                            continue
                    failures.append(f"published generation was unavailable: {exc}")
                    return
                time.sleep(0.001)

        thread = threading.Thread(target=reader, daemon=True)
        thread.start()
        try:
            result = self.shell(r'''
                critical() {
                    for index in $(seq 0 14); do
                        ssrp_dns_begin || return
                        printf 'ipset=/raw.example/gfwlist\n' > "$TMP_DNSMASQ_PATH/gfw.conf"
                        sleep 0.01
                        : > "$TMP_DNSMASQ_PATH/gfw.conf"
                        for row in $(seq 1 200); do
                            printf 'server=/new-%s.example/192.0.2.2\n' "$index" >> "$TMP_DNSMASQ_PATH/gfw.conf" || return
                        done
                        ssrp_dns_publish || return
                    done
                }
                ssrp_run_locked critical
            ''', check=False)
        finally:
            stop.set()
            thread.join(timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(failures, "\n".join(failures))
        self.assertGreater(read_count, 20, "reader did not overlap generation")
        self.assertTrue(any("new-" in content for content in observed),
                        "reader never observed a new published generation")
        self.assert_no_stage()

    @unittest.skipUnless(sys.platform.startswith("linux") and shutil.which("flock"),
                         "requires Linux flock; Git Bash cannot prove kernel lock semantics")
    def test_real_flock_serializes_whole_restart_not_individual_halves(self):
        self.shell(r'''
            ssrp_stop() {
                printf '%s stop\n' "$1" >> "$TEST_ROOT/order"
                sleep 0.1
            }
            ssrp_start() {
                printf '%s start\n' "$1" >> "$TEST_ROOT/order"
                sleep 0.1
            }
            ssrp_run_locked ssrp_restart_locked A & first=$!
            ssrp_run_locked ssrp_restart_locked B & second=$!
            wait "$first" || exit
            wait "$second"
        ''', programs="")
        order = (self.base / "order").read_text().splitlines()
        self.assertIn(order, (["A stop", "A start", "B stop", "B start"],
                              ["B stop", "B start", "A stop", "A start"]))

    @unittest.skipUnless(sys.platform.startswith("linux") and shutil.which("flock"),
                         "requires Linux flock and /proc for process-death recovery")
    def test_real_flock_recovers_after_sigkill(self):
        holder_code = self.preamble + r'''
            critical() {
                printf '%s\n' "$BASHPID" > "$TEST_ROOT/holder.pid"
                while :; do sleep 0.1 9>&-; done
            }
            ssrp_run_locked critical
        '''
        holder = subprocess.Popen([BASH, "--noprofile", "--norc", "-c", holder_code],
                                  env=self.env, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 5
            pid_file = self.base / "holder.pid"
            while not pid_file.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(pid_file.exists(), "lock holder did not start")
            owner = int(pid_file.read_text())
            os.kill(owner, 9)
            self.shell("ssrp_run_locked true", programs="", timeout=5)
        finally:
            holder.kill() if holder.poll() is None else None
            holder.wait(timeout=5)

    @unittest.skipUnless(sys.platform.startswith("linux") and shutil.which("dnsmasq"),
                         "requires an installed dnsmasq binary for real parser validation")
    def test_installed_dnsmasq_rejects_invalid_configuration_without_publish(self):
        result = self.shell(r'''
            critical() {
                ssrp_dns_begin || return
                printf 'not-a-dnsmasq-option=value\n' > "$TMP_DNSMASQ_PATH/invalid.conf"
                ssrp_dns_publish
            }
            ssrp_run_locked critical
        ''', programs="flock() { return 0; }\n", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assert_old_generation()
        self.assert_no_stage()


if __name__ == "__main__":
    unittest.main()
