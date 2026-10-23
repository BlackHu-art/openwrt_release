#!/usr/bin/env python3
# Historical 190-r12 regression only; production v198.2 coverage is test_ssrplus_v198.py.
"""Exercise the imported SSR shell scripts in an isolated local filesystem.

Never contacts a router. Dependency programs are replaced only at OS boundaries;
the lifecycle and rule-generation bodies come from the reviewed upstream files.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/ssrplus/2abdc9aa"


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ssrplus-runtime-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.package = self.base / "package"
        self.init = self.package / "root/etc/init.d/shadowsocksr"
        self.generator = self.package / "root/usr/share/shadowsocksr/gfw2ipset.sh"
        self.init.parent.mkdir(parents=True)
        self.generator.parent.mkdir(parents=True)
        shutil.copyfile(FIXTURE / "shadowsocksr.init", self.init)
        shutil.copyfile(FIXTURE / "gfw2ipset.sh", self.generator)
        shutil.copyfile(FIXTURE / "update.lua", self.generator.parent / "update.lua")
        shutil.copyfile(FIXTURE / "Makefile", self.package / "Makefile")
        rules = self.package / "root/usr/bin/ssr-rules"
        rules.parent.mkdir(parents=True)
        shutil.copyfile(ROOT / "tests/fixtures/ssrplus-persistence/2abdc9aa/ssr-rules", rules)
        self.bash = shutil.which("bash") or "bash"
        if os.name == "nt":
            self.bash = "C:/Program Files/Git/usr/bin/bash.exe"
        self.env = os.environ.copy()
        # Native Git must receive converted /tmp paths from the MSYS shell.
        # The test inputs are positional arguments, never shell substitutions.
        self.env.pop("MSYS_NO_PATHCONV", None)
        self.env["TEST_ROOT"] = self.base.as_posix()
        if os.name == "nt":
            flock_dir = os.environ.get("SSRP_TEST_FLOCK_DIR", str(Path(tempfile.gettempdir()) /
                "codex-ssr-msys-flock-probe/usr/bin"))
            self.env["PATH"] = (flock_dir + os.pathsep +
                "C:/Program Files/Git/usr/bin" + os.pathsep + self.env["PATH"])
        # The separate compatibility suite exercises the production build hook
        # and source guard. Apply these exact artifacts with native Git here so
        # every behavior test need not repeat the expensive build-source audit.
        for patch in ("ssrplus-startup-lock.patch", "ssrplus-dns-transaction.patch"):
            result = subprocess.run([
                shutil.which("git") or "git", "-c", "core.autocrlf=false",
                "-C", str(self.package), "apply", str(ROOT / "tests/fixtures/ssrplus-legacy/wrt_core/patches" / patch),
            ], capture_output=True, text=True, encoding="utf-8", timeout=20)
            if result.returncode:
                self.fail(result.stderr)
        shutil.copyfile(ROOT / "tests/fixtures/ssrplus-legacy/wrt_core/compat/ssrplus/runtime.sh",
                        self.generator.parent / "ssrp-runtime.sh")
        # Relocate fixed system dependencies only. The scripts' function bodies
        # and their sequencing are exercised unmodified.
        text = self.init.read_text(encoding="utf-8")
        text = text.replace('${IPKG_INSTROOT:-}/usr/share/shadowsocksr/ssrp-runtime.sh',
                            (ROOT / "tests/fixtures/ssrplus-legacy/wrt_core/compat/ssrplus/runtime.sh").as_posix())
        self.sourced_init = self.base / "init-test.sh"
        text = text.replace('LOG_FILE=/var/log/ssrplus.log', 'LOG_FILE="$TEST_ROOT/ssrplus.log"')
        text = text.replace('CRON_FILE=/etc/crontabs/root', 'CRON_FILE="$TEST_ROOT/crontab"')
        text = text.replace('TMP_PATH=/var/etc/ssrplus', 'TMP_PATH="$TEST_ROOT/service"')
        self.sourced_init.write_text(text, encoding="utf-8", newline="\n")

    def generator_script(self):
        data = self.base / "data"
        data.mkdir()
        inputs = {
            "gfw_list.conf": "server=/public.example/127.0.0.1#5335\nipset=/public.example/gfwlist\n",
            "gfw_base.conf": "server=/base.example/127.0.0.1#5335\nipset=/base.example/gfwlist\n",
            "oversea_list.conf": "server=/oversea.example/127.0.0.1#5335\nipset=/oversea.example/oversea\n",
            "black.list": "forced.example\n",
            "white.list": "internal.example\n",
            "deny.list": "blocked.example\n",
            "netflix.list": "netflix.example\n",
            "ad.conf": "address=/ads.example/\naddress=/internal.example/\n",
        }
        for name, content in inputs.items():
            (data / name).write_text(content, encoding="utf-8", newline="\n")
        with self.sourced_init.open("a", encoding="utf-8", newline="\n") as file:
            file.write(r'''
DNSMASQ_CONF_DIR="$TEST_ROOT/dnsmasq.d"
TMP_DNSMASQ_PATH="$TEST_ROOT/legacy"
check_run_environment() { USE_TABLES=nftables; DNSMASQ_NFTSET=1; DNSMASQ_IPSET=0; }
echolog() { :; }
uci_get_by_type() {
    case "$2" in
        run_mode) echo "${TEST_RUN_MODE:-gfw}" ;;
        netflix_enable|adblock) echo 1 ;;
        netflix_server) echo same ;;
        global_server) echo company ;;
        *) echo "${3:-}" ;;
    esac
}
''')
        text = self.generator.read_text(encoding="utf-8")
        text = text.replace('. $IPKG_INSTROOT/etc/init.d/shadowsocksr',
                            '. "$SSRP_TEST_INIT"')
        text = text.replace('/etc/ssrplus/', data.as_posix() + '/')
        test_generator = self.base / "gfw-test.sh"
        test_generator.write_text(text, encoding="utf-8", newline="\n")
        self.env["SSRP_TEST_INIT"] = self.sourced_init.as_posix()
        self.env["SSRP_TEST_GENERATOR"] = test_generator.as_posix()
        return data

    def run_shell(self, code, *args, check=True):
        result = subprocess.run(
            [self.bash, "--noprofile", "--norc", "-c", code, "test", *args],
            env=self.env, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=20,
        )
        if check and result.returncode:
            self.fail(f"shell exited {result.returncode}: {result.stdout}\n{result.stderr}")
        return result

    def test_failed_lock_does_not_enter_start_body(self):
        result = self.run_shell(r'''
            source "$1"
            LOCK_FILE="$TEST_ROOT/lifecycle.lock"
            flock() { return 1; }
            echolog() { printf 'entered\n' >> "$TEST_ROOT/entered"; exit 42; }
            start
        ''', self.sourced_init.as_posix(), check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.base / "entered").exists(),
                         "start continued into its body after flock failed")

    def helper(self):
        return (ROOT / "tests/fixtures/ssrplus-legacy/wrt_core/compat/ssrplus/runtime.sh").as_posix()

    def require_flock(self):
        if not shutil.which("flock", path=self.env["PATH"]):
            self.skipTest("real flock requires util-linux or SSRP_TEST_FLOCK_DIR on Windows")

    def test_restart_serializes_stop_and_start_against_other_callers(self):
        self.require_flock()
        self.run_shell(r'''
            source "$1"
            LOCK_FILE="$TEST_ROOT/lifecycle.lock"
            ssrp_stop() { echo stop >> "$TEST_ROOT/events"; sleep .15; }
            ssrp_start() { echo start >> "$TEST_ROOT/events"; }
            rival() { echo rival >> "$TEST_ROOT/events"; }
            ssrp_run_locked ssrp_restart_locked &
            first=$!
            while [ ! -f "$TEST_ROOT/events" ]; do sleep .01; done
            ssrp_run_locked rival & second=$!
            wait "$first"; wait "$second"
            [ -f "$LOCK_FILE" ]
        ''', self.helper())
        self.assertEqual((self.base / "events").read_text().splitlines(),
                         ["stop", "start", "rival"])

    def test_daemon_does_not_retain_lifecycle_lock(self):
        self.require_flock()
        self.run_shell(r'''
            source "$1"
            LOCK_FILE="$TEST_ROOT/lifecycle.lock"
            source "$2"
            LOCK_FILE="$TEST_ROOT/lifecycle.lock"
            TMP_BIN_PATH="$TEST_ROOT/bin"
            mkdir -p "$TMP_BIN_PATH"
            daemon_pid=
            owner_pid=
            cleanup() {
                local result=$?
                trap - EXIT
                [ -z "$daemon_pid" ] || kill -TERM "$daemon_pid" 2>/dev/null || :
                [ -z "$owner_pid" ] || wait "$owner_pid" 2>/dev/null || :
                exit "$result"
            }
            trap cleanup EXIT
            work() {
                ln_start_bin "$(command -v sleep)" test-sleeper 30
                local child_pid=$! result
                # Keep the launch owner alive so it can reap its actual child.
                # Releasing only the owner's FD still exposes daemon leakage:
                # an inherited FD9 makes the rival flock below fail.
                exec 9>&-
                printf '%s\n' "$child_pid" > "$TEST_ROOT/daemon"
                wait "$child_pid"
                result=$?
                [ "$result" = 143 ] || return "$result"
            }
            ssrp_run_locked work &
            owner_pid=$!
            for attempt in $(seq 1 500); do
                [ ! -s "$TEST_ROOT/daemon" ] || break
                command sleep .01
            done
            [ -s "$TEST_ROOT/daemon" ] || exit 56
            daemon_pid=$(cat "$TEST_ROOT/daemon")
            kill -0 "$daemon_pid" || exit 57
            exec 8>>"$LOCK_FILE"
            flock -xn 8 || exit 55
            kill -TERM "$daemon_pid" || exit 58
            wait "$owner_pid" || exit 59
            owner_pid=
            daemon_pid=
        ''', self.helper(), self.sourced_init.as_posix())

    def test_command_failure_preserves_inode_and_releases_lock(self):
        self.require_flock()
        self.run_shell(r'''
            source "$1"
            LOCK_FILE="$TEST_ROOT/lifecycle.lock"
            fail() { return 23; }
            ssrp_run_locked fail; result=$?
            [ "$result" = 23 ] || exit 60
            old=$(ls -i "$LOCK_FILE")
            ssrp_run_locked true || exit 61
            [ "$old" = "$(ls -i "$LOCK_FILE")" ] || exit 62
        ''', self.helper())

    def dns_script(self):
        return r'''
            source "$1"
            DNSMASQ_CONF_DIR="$TEST_ROOT/dnsmasq.d"
            TMP_DNSMASQ_PATH="$TEST_ROOT/legacy"
            mkdir -p "$DNSMASQ_CONF_DIR"
            printf 'server=/old.example/192.0.2.1\n' > "$DNSMASQ_CONF_DIR/dnsmasq-ssrplus.conf"
            # Boundary substitute: deliberately represents a no-ipset parser.
            # Linux CI can also run this bundle through a real dnsmasq binary.
            dnsmasq() {
                local file=${2#--conf-file=}
                if [ "${SSRP_REAL_DNSMASQ:-0}" = 1 ]; then
                    command dnsmasq "$@"
                else
                    ! grep -Eq '^(ipset=|INVALID)' "$file"
                fi
            }
        '''

    def test_dns_validation_failure_keeps_last_complete_config(self):
        self.run_shell(self.dns_script() + r'''
            before=$(cat "$DNSMASQ_CONF_DIR/dnsmasq-ssrplus.conf")
            ssrp_dns_begin
            echo 'ipset=/bad.example/gfwlist' > "$TMP_DNSMASQ_PATH/gfw.conf"
            echo INVALID >> "$TMP_DNSMASQ_PATH/gfw.conf"
            if ssrp_dns_publish; then exit 63; fi
            [ "$before" = "$(cat "$DNSMASQ_CONF_DIR/dnsmasq-ssrplus.conf")" ] || exit 64
            ssrp_dns_abort
            [ -z "$(find "$DNSMASQ_CONF_DIR" -name '.ssrplus-dns.*')" ]
        ''', self.helper())

    def test_dns_single_publish_rename_failure_preserves_old_config(self):
        self.run_shell(self.dns_script() + r'''
            before=$(cat "$DNSMASQ_CONF_DIR/dnsmasq-ssrplus.conf")
            ssrp_dns_begin
            echo 'server=/new.example/192.0.2.2' > "$TMP_DNSMASQ_PATH/gfw.conf"
            mv() { return 1; }
            if ssrp_dns_publish; then exit 65; fi
            [ "$before" = "$(cat "$DNSMASQ_CONF_DIR/dnsmasq-ssrplus.conf")" ] || exit 66
            ssrp_dns_abort
        ''', self.helper())

    def test_dns_readers_never_observe_unfinished_or_mixed_bundle(self):
        self.run_shell(self.dns_script() + r'''
            old=$(cat "$DNSMASQ_CONF_DIR/dnsmasq-ssrplus.conf")
            new=$(printf 'server=/new.example/192.0.2.2\nnftset=/new.example/inet#ss_spec#gfwlist')
            (
                while [ ! -f "$TEST_ROOT/finished" ]; do
                    value=$(cat "$DNSMASQ_CONF_DIR/dnsmasq-ssrplus.conf")
                    [ "$value" = "$old" ] || [ "$value" = "$new" ] || {
                        echo "$value" > "$TEST_ROOT/partial"; break;
                    }
                done
            ) & reader=$!
            ssrp_dns_begin
            echo 'server=/new.example/192.0.2.2' > "$TMP_DNSMASQ_PATH/gfw.conf"
            sleep .1
            echo 'nftset=/new.example/inet#ss_spec#gfwlist' >> "$TMP_DNSMASQ_PATH/gfw.conf"
            ssrp_dns_publish || exit 67
            touch "$TEST_ROOT/finished"; wait "$reader"
            [ ! -f "$TEST_ROOT/partial" ] || exit 68
            [ "$new" = "$(cat "$DNSMASQ_CONF_DIR/dnsmasq-ssrplus.conf")" ]
        ''', self.helper())

    def test_real_generator_converts_no_ipset_rules_and_keeps_inputs_clean(self):
        data = self.generator_script()
        before = {path.name: path.read_bytes() for path in data.iterdir()}
        self.run_shell(self.dns_script() + r'''
            ssrp_dns_begin
            SSRP_DNS_STAGE="$TMP_DNSMASQ_PATH" bash "$SSRP_TEST_GENERATOR" || exit 71
            ! grep -Rh '^ipset=' "$TMP_DNSMASQ_PATH" || exit 72
            grep -q 'nftset=/public.example/inet#ss_spec#gfwlist' "$TMP_DNSMASQ_PATH/gfw_list.conf" || exit 73
            grep -q 'nftset=/forced.example/inet#ss_spec#blacklist' "$TMP_DNSMASQ_PATH/blacklist_forward.conf" || exit 74
            ! grep -q internal.example "$TMP_DNSMASQ_PATH/ad.conf" || exit 75
            ssrp_dns_publish || exit 76
        ''', self.helper())
        self.assertEqual(before, {path.name: path.read_bytes() for path in data.iterdir()})

    def test_real_generator_missing_input_preserves_active_config(self):
        data = self.generator_script()
        (data / "gfw_base.conf").unlink()
        self.run_shell(self.dns_script() + r'''
            before=$(cat "$DNSMASQ_CONF_DIR/dnsmasq-ssrplus.conf")
            ssrp_dns_begin
            if SSRP_DNS_STAGE="$TMP_DNSMASQ_PATH" bash "$SSRP_TEST_GENERATOR"; then exit 77; fi
            [ "$before" = "$(cat "$DNSMASQ_CONF_DIR/dnsmasq-ssrplus.conf")" ] || exit 78
            ssrp_dns_abort
        ''', self.helper())

    def test_real_generator_router_mode_strips_all_set_directives(self):
        self.generator_script()
        self.env["TEST_RUN_MODE"] = "router"
        self.run_shell(self.dns_script() + r'''
            ssrp_dns_begin
            SSRP_DNS_STAGE="$TMP_DNSMASQ_PATH" bash "$SSRP_TEST_GENERATOR" || exit 79
            ! grep -E '^(ipset|nftset)=' "$TMP_DNSMASQ_PATH/gfw_list.conf" || exit 80
            ssrp_dns_publish || exit 81
        ''', self.helper())

    def test_no_node_adblock_copy_failure_keeps_active_config(self):
        data = self.generator_script()
        text = self.sourced_init.read_text(encoding="utf-8")
        text = text.replace('/var/run /var/lock /var/log', '"$TEST_ROOT/run" "$TEST_ROOT/lock" "$TEST_ROOT/log"')
        text = text.replace('/etc/ssrplus/', data.as_posix() + '/')
        text = text.replace('/etc/init.d/dnsmasq restart', 'restart_dnsmasq')
        self.sourced_init.write_text(text, encoding="utf-8", newline="\n")
        self.run_shell(self.dns_script() + r'''
            source "$SSRP_TEST_INIT"
            TMP_BIN_PATH="$TEST_ROOT/bin"
            check_run_environment() { :; }
            load_config() { return 1; }
            check_server() { :; }; start_server() { :; }; start_monitor() { :; }
            clean_log() { :; }; restart_dnsmasq() { :; }; ssrp_dnsmasq() { :; }
            cp() { case "$1 $2" in *ad.conf*) return 1;; *) command cp "$@";; esac; }
            before=$(cat "$DNSMASQ_CONF_DIR/dnsmasq-ssrplus.conf")
            if ssrp_start; then exit 82; fi
            [ "$before" = "$(cat "$DNSMASQ_CONF_DIR/dnsmasq-ssrplus.conf")" ] || exit 83
            ssrp_dns_abort
        ''', self.helper())

    def test_missing_selected_node_is_resolved_before_loading_configuration(self):
        data = self.generator_script()
        text = self.sourced_init.read_text(encoding="utf-8")
        text = text.replace('/var/run /var/lock /var/log', '"$TEST_ROOT/run" "$TEST_ROOT/lock" "$TEST_ROOT/log"')
        text = text.replace('/etc/ssrplus/', data.as_posix() + '/')
        text = text.replace('/etc/init.d/dnsmasq restart', 'restart_dnsmasq')
        self.sourced_init.write_text(text, encoding="utf-8", newline="\n")
        self.run_shell(self.dns_script() + r'''
            source "$SSRP_TEST_INIT"
            TMP_BIN_PATH="$TEST_ROOT/bin"
            check_run_environment() { :; }
            uci_get_by_name() { echo nil; }
            uci_get_by_cfgid() { echo fallback; }
            uci_set_by_type() { selected="$3"; }
            load_config() { [ "${selected:-}" = fallback ] || exit 84; return 1; }
            start_server() { :; }; start_monitor() { :; }
            clean_log() { :; }; restart_dnsmasq() { :; }; ssrp_dnsmasq() { :; }
            ssrp_start || exit 85
        ''', self.helper())

    def test_updater_lua_syntax_with_installed_parser(self):
        parser = shutil.which("luac") or shutil.which("luac5.1")
        if not parser:
            self.skipTest("luac is unavailable; Linux CI installs lua5.1")
        result = subprocess.run([parser, "-p", str(self.generator.parent / "update.lua")],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_real_start_dns_apple_copy_failure_preserves_active(self):
        data = self.generator_script()
        (data / "applechina.conf").write_text("server=/apple.example/192.0.2.2\n", encoding="utf-8")
        text = self.sourced_init.read_text(encoding="utf-8").replace('/etc/ssrplus/', data.as_posix() + '/')
        self.sourced_init.write_text(text, encoding="utf-8", newline="\n")
        self.run_shell(self.dns_script() + r'''
            source "$SSRP_TEST_INIT"
            uci_get_by_type() {
                case "$2" in apple_optimization) echo 1;; pdnsd_enable) echo 0;; *) echo '';; esac
            }
            before=$(cat "$DNSMASQ_CONF_DIR/dnsmasq-ssrplus.conf")
            ssrp_dns_begin
            cp() { return 47; }
            if start_dns; then exit 86; fi
            [ "$before" = "$(cat "$DNSMASQ_CONF_DIR/dnsmasq-ssrplus.conf")" ] || exit 87
            ssrp_dns_abort
        ''', self.helper())

    def test_real_start_dns_apple_transforms_only_private_copy(self):
        data = self.generator_script()
        original = "server=/apple.example/192.0.2.2\n"
        apple = data / "applechina.conf"
        apple.write_text(original, encoding="utf-8")
        text = self.sourced_init.read_text(encoding="utf-8").replace('/etc/ssrplus/', data.as_posix() + '/')
        self.sourced_init.write_text(text, encoding="utf-8", newline="\n")
        for fail_sed in (True, False):
            with self.subTest(fail_sed=fail_sed):
                self.env["FAIL_APPLE_SED"] = str(int(fail_sed))
                self.run_shell(self.dns_script() + r'''
                    source "$SSRP_TEST_INIT"
                    uci_get_by_type() {
                        case "$2" in
                            apple_optimization) echo 1;; pdnsd_enable) echo 0;;
                            apple_dns) echo 192.0.2.8;; *) echo '';;
                        esac
                    }
                    ssrp_dns_begin
                    if [ "$FAIL_APPLE_SED" = 1 ]; then
                        sed() { return 49; }
                        if start_dns; then exit 89; fi
                        ssrp_dns_abort
                    else
                        start_dns || exit 90
                        grep -q 'server=/apple.example/192.0.2.8' "$TMP_DNSMASQ_PATH/applechina.conf" || exit 91
                        ssrp_dns_publish || exit 92
                    fi
                ''', self.helper())
                self.assertEqual(apple.read_text(encoding="utf-8"), original)
        apple.write_text("", encoding="utf-8")
        self.run_shell(self.dns_script() + r'''
            source "$SSRP_TEST_INIT"
            uci_get_by_type() {
                case "$2" in apple_optimization) echo 1;; pdnsd_enable) echo 0;; apple_dns) echo 192.0.2.8;; *) echo '';; esac
            }
            ssrp_dns_begin
            start_dns || exit 93
            [ -f "$TMP_DNSMASQ_PATH/applechina.conf" ] && [ ! -s "$TMP_DNSMASQ_PATH/applechina.conf" ] || exit 94
            ssrp_dns_publish
        ''', self.helper())

    def test_real_stop_waits_for_all_kill_pipelines(self):
        text = self.sourced_init.read_text(encoding="utf-8")
        text = text.replace('/usr/bin/ssr-rules', 'fake_rules')
        text = text.replace('/var/lock/', self.base.as_posix() + '/locks/')
        self.sourced_init.write_text(text, encoding="utf-8", newline="\n")
        self.run_shell(r'''
            source "$1"
            PS=fake_ps
            switch_server=''
            TMP_PATH="$TEST_ROOT/cores"
            DNSMASQ_CONF_DIR="$TEST_ROOT/no-dns"
            fake_ps() { echo '12345 ssr-switch ssr-monitor ssr-rules sleep 0000'; }
            fake_rules() { :; }; killall() { :; }; sleep() { :; }
            check_run_environment() { USE_TABLES=''; HAS_IPSET=0; }
            uci() { return 1; }; del_cron() { :; }
            xargs() {
                input=$(cat)
                if [ -n "$input" ]; then
                    command sleep .15
                    echo killed >> "$TEST_ROOT/killed"
                fi
            }
            ssrp_stop
            [ "$(wc -l < "$TEST_ROOT/killed")" = 4 ] || exit 88
        ''', self.sourced_init.as_posix())

    def test_busybox_ash_syntax_with_installed_parser(self):
        busybox = shutil.which("busybox")
        if not busybox:
            self.skipTest("BusyBox ash is unavailable; Linux CI installs busybox")
        for path in (self.init, self.generator, ROOT / "tests/fixtures/ssrplus-legacy/wrt_core/compat/ssrplus/runtime.sh"):
            result = subprocess.run([busybox, "ash", "-n", str(path)],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
