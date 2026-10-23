#!/usr/bin/env python3
# Historical 190-r12 regression only; production v198.2 coverage is test_ssrplus_v198.py.
"""Execute the complete patched monitor, switch and cron scripts locally.

Only OS boundaries (process inventory, init dispatch, UCI, daemon executables,
logging and the loop's sleep) are substituted. Monitor branch selection and
the scheduler's ordering/status propagation execute as shipped. No router is
contacted; real Linux lock serialization remains a separate acceptance check.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/ssrplus/2abdc9aa"
PATCH = ROOT / "tests/fixtures/ssrplus-legacy/wrt_core/patches/ssrplus-monitor-scheduler.patch"
BASH = os.environ.get("BASH") or shutil.which("bash")
if os.name == "nt" and not BASH:
    BASH = "C:/Program Files/Git/bin/bash.exe"


def relocate_locked_init(source, root, runtime):
    source = re.sub(r"/(?:etc|var|tmp)/",
                    lambda match: root + match.group(0), source)
    source = source.replace("/usr/bin/ssr-rules", "test_ssr_rules")
    source = source.replace("/bin/busybox", "busybox")
    # Inject host paths last: Linux temporary directories also start with /tmp/.
    return source.replace('${IPKG_INSTROOT:-}/usr/share/shadowsocksr/ssrp-runtime.sh',
                          runtime)


class InitBoundaryRelocationRegressions(unittest.TestCase):
    def test_posix_runtime_path_is_not_relocated_twice(self):
        source = ('. "${IPKG_INSTROOT:-}/usr/share/shadowsocksr/ssrp-runtime.sh"\n'
                  'LOG_FILE="/var/log/ssrplus.log"\n'
                  'CONFIG="/etc/config/shadowsocksr"\n'
                  'WORK="/tmp/ssrplus"\n')
        relocated = relocate_locked_init(source, "/tmp/ssrplus-monitor-test",
                                         "/tmp/ssrplus-monitor-test/runtime.sh")
        self.assertEqual(relocated,
                         '. "/tmp/ssrplus-monitor-test/runtime.sh"\n'
                         'LOG_FILE="/tmp/ssrplus-monitor-test/var/log/ssrplus.log"\n'
                         'CONFIG="/tmp/ssrplus-monitor-test/etc/config/shadowsocksr"\n'
                         'WORK="/tmp/ssrplus-monitor-test/tmp/ssrplus"\n')


@unittest.skipUnless(BASH, "Bash is required to execute the upstream scripts")
class MonitorSchedulerRegressions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ssrplus-monitor-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.package = self.base / "package"
        self.bin = self.package / "root/usr/bin"
        self.share = self.package / "root/usr/share/shadowsocksr"
        self.bin.mkdir(parents=True)
        self.share.mkdir(parents=True)
        for name in ("ssr-monitor", "ssr-switch"):
            shutil.copyfile(FIXTURES / name, self.bin / name)
        shutil.copyfile(FIXTURES / "ssrplusupdate.sh", self.share / "ssrplusupdate.sh")
        self.real_init = self.base / "shadowsocksr.init"
        shutil.copyfile(FIXTURES / "shadowsocksr.init", self.real_init)
        self.command(["git", "init", "-q", str(self.package)])
        if PATCH.exists():
            self.command(["git", "-C", str(self.package), "apply", str(PATCH)])
        self.env = os.environ.copy()
        self.env.update(MSYS_NO_PATHCONV="1", TEST_ROOT=self.base.as_posix(),
                        SSR_REAL_INIT=self.real_init.as_posix())
        self.daemons = self.base / "daemons"
        self.daemons.mkdir()
        for name in ("dns2tcp", "dns2socks", "dns2socks-rust", "mosdns",
                     "dnsproxy", "chinadns-ng", "microsocks"):
            daemon = self.daemons / name
            daemon.write_text('#!/bin/sh\necho "$0 $*" >> "$TEST_ROOT/direct-launch"\n',
                              encoding="utf-8", newline="\n")
            daemon.chmod(0o755)
        self.env["PATH"] = self.daemons.as_posix() + os.pathsep + self.env["PATH"]
        (self.base / "service/bin").mkdir(parents=True)
        (self.base / "rules").mkdir()
        (self.base / "rules/dnsproxy_dns.list").write_text("tls://192.0.2.1\n")
        (self.base / "processes").write_text("")
        wrapper = self.base / "init-boundary.sh"
        wrapper.write_text(r'''
. "$SSR_REAL_INIT"
LOG_FILE="$TEST_ROOT/service.log"
TMP_PATH="$TEST_ROOT/service"
TMP_BIN_PATH="$TMP_PATH/bin"
''', encoding="utf-8", newline="\n")
        self.env["SSR_INIT"] = wrapper.as_posix()
        for name in ("ssr-monitor", "ssr-switch"):
            target = self.bin / name
            source = target.read_text(encoding="utf-8")
            source = source.replace('. $IPKG_INSTROOT/etc/init.d/shadowsocksr', '. "$SSR_INIT"')
            source = source.replace('/var/lock/ssr-monitor.lock', self.base.as_posix() + '/monitor.lock')
            source = source.replace('/var/lock/ssr-switch.lock', self.base.as_posix() + '/switch.lock')
            source = source.replace('/var/log/ssrplus.log', self.base.as_posix() + '/service.log')
            source = source.replace('/etc/init.d/shadowsocksr restart', 'test_lifecycle restart')
            source = source.replace('/usr/bin/kcptun-client', 'test_daemon kcptun-client')
            source = source.replace('/usr/bin/ssr-check', 'test_ssr_check')
            source = source.replace('/etc/ssrplus/', self.base.as_posix() + '/rules/')
            source = source.replace('/var/run', self.base.as_posix() + '/run')
            source = source.replace('/var/etc', self.base.as_posix() + '/etc')
            target.write_text(source, encoding="utf-8", newline="\n")
        self.env.update(SSR_MONITOR=(self.bin / "ssr-monitor").as_posix(),
                        SSR_SWITCH=(self.bin / "ssr-switch").as_posix())

    def command(self, argv):
        result = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def shell(self, body, *, settings=None, args=(), asynchronous=False):
        env = self.env.copy()
        env.update(settings or {})
        preamble = r'''
sleep_count=0
trap 'wait' EXIT
ulimit() { :; }
sleep() {
    case "$1" in 0000*) ;; *) return 0 ;; esac
    sleep_count=$((sleep_count + 1))
    [ "$sleep_count" -lt 2 ] || exit 0
}
busybox() { [ "$*" = "ps -w" ] || return 64; cat "$TEST_ROOT/processes"; }
logger() { printf '%s\n' "$*" >> "$TEST_ROOT/logger"; }
kill() { echo "kill $*" >> "$TEST_ROOT/direct-kill"; }
killall() { echo "killall $*" >> "$TEST_ROOT/direct-kill"; }
test_daemon() { echo "$*" >> "$TEST_ROOT/direct-launch"; }
test_lifecycle() {
    printf '%s\n' "$*" >> "$TEST_ROOT/lifecycle"
    return "${LIFECYCLE_STATUS:-0}"
}
uci() {
    case "$*" in
        *._unused_ssrp_changed*) echo "${CHINA_DNS_ENABLED:-0}" ;;
        *run_mode*) echo "${RUN_MODE:-gfw}" ;;
        *pdnsd_enable*) echo "${PDNSD_ENABLE:-0}" ;;
        *chinadns_forward*) echo "${CHINADNS_FORWARD:-}" ;;
        *global_server*) echo main ;;
        *kcp_enable*) echo 0 ;;
        *switch_try_count*) echo 1 ;;
        *switch_enable*) echo 1 ;;
        *parse_method*) echo parse_file ;;
        *dnsproxy_ipv6*) echo 0 ;;
        *server_port*) echo 443 ;;
        *server*) echo 192.0.2.1 ;;
    esac
}
test_ssr_check() {
    case "$1" in www.google.com) return 1 ;; *) return 0 ;; esac
}
ipset() { :; }
tcping() { return 0; }
config_load() { :; }
config_foreach() { "$1" backup; }
'''
        argv = [BASH, "--noprofile", "--norc", "-c", preamble + body,
                "test-shell", *map(str, args)]
        if asynchronous:
            return subprocess.Popen(argv, env=env, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True,
                                    encoding="utf-8", errors="replace")
        return subprocess.run(argv, env=env, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=30)

    def lines(self, name):
        path = self.base / name
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    def monitor(self, mode, processes="", *, settings=None, counts=(0, 0, 0, 0, 0)):
        (self.base / "processes").write_text(processes, encoding="utf-8", newline="\n")
        return self.shell('. "$SSR_MONITOR" "$@"\n', settings=settings,
                          args=(*counts, mode))

    def assert_recovery(self, result, *, status=0):
        self.assertEqual(result.returncode, status, result.stderr)
        self.assertEqual(self.lines("lifecycle"), ["restart"],
                         "a missing component must trigger exactly one lifecycle restart")
        self.assertEqual(self.lines("direct-launch"), [],
                         "monitor launched a daemon outside the lifecycle lock")
        self.assertEqual(self.lines("direct-kill"), [],
                         "monitor killed a daemon outside the lifecycle lock")
        self.assertFalse((self.base / "service/cleaned_dns.list").exists())
        self.assertFalse((self.base / "service/temp_dns.list").exists())

    def test_mode2_detects_dead_dns2socks_with_live_microsocks(self):
        self.assert_recovery(self.monitor(2, "101 microsocks -p 300 ssrplus-dns\n"))

    def test_mode2_detects_dead_microsocks_with_live_dns2socks(self):
        self.assert_recovery(self.monitor(2, "102 dns2socks 127.0.0.1:300 8.8.4.4:53\n"))

    def test_mode2_accepts_both_observed_argv_formats_when_both_are_alive(self):
        for address in ("127.0.0.1:300", "127.0.0.1 300"):
            with self.subTest(address=address):
                (self.base / "monitor.lock").unlink(missing_ok=True)
                result = self.monitor(2, "101 microsocks -p 300 ssrplus-dns\n"
                                      f"102 dns2socks {address} 8.8.4.4:53\n")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.lines("lifecycle"), [])

    def test_mode3_detects_each_missing_component(self):
        for processes in ("101 microsocks -p 300 ssrplus-dns\n",
                          "102 dns2socks-rust -s socks5://127.0.0.1:300\n"):
            with self.subTest(processes=processes):
                (self.base / "monitor.lock").unlink(missing_ok=True)
                (self.base / "lifecycle").unlink(missing_ok=True)
                self.assert_recovery(self.monitor(3, processes))

    def test_mode4_missing_mosdns_restarts_through_lifecycle(self):
        self.assert_recovery(self.monitor(4))

    def test_mode5_missing_dnsproxy_is_reachable_with_unrelated_microsocks_alive(self):
        self.assert_recovery(self.monitor(5, "101 microsocks -p 300 ssrplus-dns\n"))

    def test_modes4_and5_do_not_restart_healthy_components(self):
        for mode, process in ((4, f"101 {self.base.as_posix()}/service/bin/mosdns start\n"),
                              (5, "101 dnsproxy -l 127.0.0.1 -p 300 -p 5335\n")):
            with self.subTest(mode=mode):
                (self.base / "monitor.lock").unlink(missing_ok=True)
                result = self.monitor(mode, process)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.lines("lifecycle"), [])

    def test_other_monitor_recoveries_do_not_launch_or_kill_outside_lock(self):
        for mode, counts, settings in ((1, (0, 0, 0, 0, 0), {}),
                                      (6, (0, 0, 0, 0, 0), {}),
                                      (0, (0, 0, 0, 0, 0), {"RUN_MODE": "router", "PDNSD_ENABLE": "1", "CHINADNS_FORWARD": "wan"}),
                                      (0, (1, 0, 0, 0, 0), {}),
                                      (0, (0, 1, 0, 0, 0), {}),
                                      (0, (0, 0, 1, 0, 0), {}),
                                      (0, (0, 0, 0, 1, 0), {}),
                                      (0, (0, 0, 0, 0, 1), {})):
            with self.subTest(mode=mode, counts=counts, settings=settings):
                (self.base / "monitor.lock").unlink(missing_ok=True)
                (self.base / "lifecycle").unlink(missing_ok=True)
                self.assert_recovery(self.monitor(mode, counts=counts, settings=settings))

    def test_failed_monitor_restart_returns_failure_and_is_not_retried(self):
        self.assert_recovery(self.monitor(2, settings={"LIFECYCLE_STATUS": "23"}), status=23)

    def test_fresh_router_config_detects_dead_5333_without_legacy_dhcp_marker(self):
        settings = {"RUN_MODE": "router", "PDNSD_ENABLE": "2",
                    "CHINADNS_FORWARD": "wan", "CHINA_DNS_ENABLED": "0"}
        self.assert_recovery(self.monitor(2, "101 microsocks -p 300 ssrplus-dns\n"
                                          "102 dns2socks 127.0.0.1:300 8.8.4.4:53\n",
                                          settings=settings))

    def test_live_proxy_chinadns_does_not_mask_dead_5333_listener(self):
        settings = {"RUN_MODE": "router", "PDNSD_ENABLE": "6",
                    "CHINADNS_FORWARD": "wan", "CHINA_DNS_ENABLED": "1"}
        process = f"101 {self.base.as_posix()}/service/bin/chinadns-ng -b 127.0.0.1 -l 300 -l 5335 -p 3\n"
        self.assert_recovery(self.monitor(6, process, settings=settings))

    def test_fresh_router_config_accepts_healthy_5333_listener(self):
        settings = {"RUN_MODE": "router", "PDNSD_ENABLE": "6",
                    "CHINADNS_FORWARD": "wan", "CHINA_DNS_ENABLED": "0"}
        processes = (f"101 {self.base.as_posix()}/service/bin/chinadns-ng -b 127.0.0.1 -l 300 -l 5335 -p 3\n"
                     f"102 {self.base.as_posix()}/service/bin/chinadns-ng -l 5333 -4 china -p 3\n")
        result = self.monitor(6, processes, settings=settings)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.lines("lifecycle"), [])

    def test_legacy_dhcp_marker_alone_does_not_enable_5333_monitoring(self):
        for settings in ({"RUN_MODE": "gfw", "PDNSD_ENABLE": "1", "CHINADNS_FORWARD": "wan"},
                         {"RUN_MODE": "router", "PDNSD_ENABLE": "0", "CHINADNS_FORWARD": "wan"},
                         {"RUN_MODE": "router", "PDNSD_ENABLE": "1", "CHINADNS_FORWARD": ""}):
            with self.subTest(settings=settings):
                (self.base / "monitor.lock").unlink(missing_ok=True)
                result = self.monitor(0, settings={**settings, "CHINA_DNS_ENABLED": "1"})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.lines("lifecycle"), [])

    def test_monitor_recovery_queues_behind_concurrent_stop_before_any_activation(self):
        # Execute real public stop/restart and their bodies. The flock OS
        # boundary holds stop until released, and queues restart behind it.
        # This proves the shared lifecycle route, not kernel flock semantics.
        init = self.package / "root/etc/init.d/shadowsocksr"
        init.parent.mkdir(parents=True)
        shutil.copyfile(FIXTURES / "shadowsocksr.init", init)
        for name in ("gfw2ipset.sh", "update.lua"):
            shutil.copyfile(FIXTURES / name, self.share / name)
        for name in ("ssrplus-startup-lock.patch", "ssrplus-dns-transaction.patch"):
            self.command(["git", "-C", str(self.package), "apply",
                          str(ROOT / "tests/fixtures/ssrplus-legacy/wrt_core/patches" / name)])
        runtime = self.base / "runtime.sh"
        runtime.write_text((ROOT / "tests/fixtures/ssrplus-legacy/wrt_core/compat/ssrplus/runtime.sh").read_text(
            encoding="utf-8").replace("/etc/init.d/dnsmasq", "test_dnsmasq"),
            encoding="utf-8", newline="\n")
        source = init.read_text(encoding="utf-8")
        source = relocate_locked_init(source, self.base.as_posix(), runtime.as_posix())
        init.write_text(source, encoding="utf-8", newline="\n")
        for directory in ("var/log", "var/lock", "etc/crontabs", "etc/ssrplus",
                          "dnsmasq.d", "tmp"):
            (self.base / directory).mkdir(parents=True, exist_ok=True)
        (self.base / "etc/ssrplus/deny.list").write_text("blocked.example\n")
        entry = self.base / "init-entry.sh"
        entry.write_text(r'''
role=$1
action=$2
shift 2
uci() {
    case "$*" in
        *global_server*) echo nil ;;
        *._unused_ssrp_changed*) echo 0 ;;
    esac
}
busybox() { :; }
ipset() { :; }
iptables() { return 1; }
nft() { return 1; }
dnsmasq() { [ "$1" != -v ] || echo 'Dnsmasq version 2.90 no-ipset no-nftset'; }
test_dnsmasq() { echo "$role dnsmasq" >> "$TEST_ROOT/order"; }
test_ssr_rules() { echo "$role rules" >> "$TEST_ROOT/order"; }
killall() { :; }
xargs() { cat >/dev/null; }
crontab() { echo "$role cron" >> "$TEST_ROOT/order"; }
sleep() { :; }
flock() {
    if [ "$role" = stop ]; then
        touch "$TEST_ROOT/stop-held"
        ready="$TEST_ROOT/release-stop"
    else
        touch "$TEST_ROOT/monitor-queued"
        ready="$TEST_ROOT/stop-done"
    fi
    for attempt in $(seq 1 1000); do
        [ ! -f "$ready" ] || return 0
        command sleep 0.01
    done
    return 1
}
. "$SSR_LOCKED_INIT"
LOCK_FILE="$TEST_ROOT/lifecycle.lock"
DNSMASQ_CONF_DIR="$TEST_ROOT/dnsmasq.d"
TMP_DNSMASQ_PATH="$TEST_ROOT/dnsmasq-ssrplus.d"
"$action" "$@"
result=$?
echo "$role complete $result" >> "$TEST_ROOT/order"
[ "$role" != stop ] || touch "$TEST_ROOT/stop-done"
exit "$result"
''', encoding="utf-8", newline="\n")
        self.env.update(SSR_LOCKED_INIT=init.as_posix(), SSR_ENTRY=entry.as_posix(),
                        TEST_BASH=str(BASH))

        def await_file(name, process):
            deadline = time.monotonic() + 10
            while not (self.base / name).exists() and time.monotonic() < deadline:
                if process.poll() is not None:
                    stdout, stderr = process.communicate(timeout=5)
                    self.fail(f"did not reach {name}: child exited {process.returncode}\n"
                              f"stdout:\n{stdout}\nstderr:\n{stderr}")
                time.sleep(0.02)
            self.assertTrue((self.base / name).exists(), f"did not reach {name}")

        stop = subprocess.Popen([BASH, "--noprofile", "--norc", str(entry), "stop", "stop"],
                                env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, encoding="utf-8", errors="replace")
        monitor = None
        try:
            await_file("stop-held", stop)
            monitor = self.shell(r'''
test_lifecycle() { "$TEST_BASH" "$SSR_ENTRY" monitor "$@"; }
. "$SSR_MONITOR" "$@"
''', args=(0, 0, 0, 0, 0, 5), asynchronous=True)
            await_file("monitor-queued", monitor)
            self.assertEqual(self.lines("order"), [],
                             "activation ran while concurrent stop held the lifecycle")
            self.assertEqual(self.lines("direct-launch"), [])
            self.assertFalse((self.base / "service/cleaned_dns.list").exists())
            (self.base / "release-stop").touch()
            stop_output = stop.communicate(timeout=15)
            monitor_output = monitor.communicate(timeout=15)
            self.assertEqual(stop.returncode, 0, str(stop_output))
            self.assertEqual(monitor.returncode, 0, str(monitor_output))
            order = self.lines("order")
            self.assertIn("monitor complete 0", order)
            self.assertLess(order.index("stop complete 0"), order.index("monitor rules"))
        finally:
            (self.base / "release-stop").touch()
            for process in (stop, monitor):
                if process is not None and process.poll() is None:
                    process.terminate()
                    process.communicate(timeout=15)

    def scheduler(self, **statuses):
        source = self.share / "ssrplusupdate.sh"
        text = source.read_text(encoding="utf-8")
        text = text.replace("/usr/bin/lua", "test_lua")
        text = text.replace("/usr/share/shadowsocksr/chinaipset.sh", "test_chinaipset")
        source.write_text(text, encoding="utf-8", newline="\n")
        self.env["SSR_SCHEDULE"] = source.as_posix()
        return self.shell(r'''
sleep() { :; }
test_lua() {
    case "$1" in
        */update.lua) echo update >> "$TEST_ROOT/stages"; return "${UPDATE_STATUS:-0}" ;;
        */subscribe.lua) echo subscribe >> "$TEST_ROOT/stages"; return "${SUBSCRIBE_STATUS:-0}" ;;
        *) return 64 ;;
    esac
}
test_chinaipset() {
    [ "$1" = /var/etc/ssrplus/china_ssr.txt ] || return 64
    echo chinaipset >> "$TEST_ROOT/stages"
    return "${CHINAIPSET_STATUS:-0}"
}
. "$SSR_SCHEDULE"
''', settings=statuses)

    def test_scheduler_stops_after_failed_rule_activation(self):
        result = self.scheduler(UPDATE_STATUS="37")
        self.assertEqual(result.returncode, 37, result.stderr)
        self.assertEqual(self.lines("stages"), ["update"])

    def test_nft_scheduler_does_not_invoke_legacy_chinaipset_without_backend_context(self):
        # The real legacy script rejects SKIP_INET=0 on nftables. update.lua
        # already activates its IP data through the checked locked reload.
        result = self.scheduler(CHINAIPSET_STATUS="38")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.lines("stages"), ["update", "subscribe"])

    def test_scheduler_propagates_subscription_failure(self):
        result = self.scheduler(SUBSCRIBE_STATUS="39")
        self.assertEqual(result.returncode, 39, result.stderr)
        self.assertEqual(self.lines("stages"), ["update", "subscribe"])

    def test_scheduler_completes_stages_in_order(self):
        result = self.scheduler()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.lines("stages"), ["update", "subscribe"])

    def test_switch_helper_propagates_failed_restart(self):
        result = self.shell('. "$SSR_SWITCH"\nswitch_proxy backup\n',
                            settings={"LIFECYCLE_STATUS": "41"})
        self.assertEqual(result.returncode, 41, result.stderr)
        self.assertEqual(self.lines("lifecycle"), ["restart backup"])

    def test_switch_does_not_claim_success_or_change_selected_node_after_failure(self):
        result = self.shell(r'''
. "$SSR_SWITCH"
start
result=$?
printf '%s\n' "$CURRENT_SERVER" > "$TEST_ROOT/selected"
exit "$result"
''', settings={"LIFECYCLE_STATUS": "41"})
        self.assertEqual(result.returncode, 41, result.stderr)
        self.assertEqual(self.lines("selected"), ["main"])
        log = "\n".join(self.lines("service.log"))
        self.assertNotIn("Switch to ", log)


if __name__ == "__main__":
    unittest.main()
