#!/usr/bin/env python3
"""Exercise bounded resolution and replacement failure boundaries locally."""
import subprocess
import unittest
import test_ssrplus_runtime_regressions as runtime_cases
ROOT = runtime_cases.ROOT


class AvailabilityTests(unittest.TestCase):
    setUp = runtime_cases.RuntimeRegressions.setUp
    shell = runtime_cases.RuntimeRegressions.shell
    assert_old_generation = runtime_cases.RuntimeRegressions.assert_old_generation
    assert_no_stage = runtime_cases.RuntimeRegressions.assert_no_stage

    def patched_sources(self):
        init, generator = runtime_cases.RuntimeRegressions.patched_sources(self)
        anchor = '${IPKG_INSTROOT:-}/usr/share/shadowsocksr/ssrp-runtime.sh'
        init.write_text(init.read_text(encoding="utf-8").replace(
            runtime_cases.RUNTIME.as_posix(), anchor), encoding="utf-8", newline="\n")
        result = subprocess.run([
            "git", "-c", "core.autocrlf=false", "-C", str(init.parents[3]),
            "apply", str(ROOT / "wrt_core/patches/ssrplus-availability.patch")],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        init.write_text(init.read_text(encoding="utf-8").replace(
            anchor, runtime_cases.RUNTIME.as_posix()), encoding="utf-8", newline="\n")
        return init, generator

    def test_resolution_fallback_has_connection_and_total_deadlines(self):
        self.patched_sources()
        self.shell(r'''
            . "$SSR_INIT" || exit
            TMP_DNSMASQ_PATH="$TEST_ROOT/dnsmasq-ssrplus.d"
            uci_get_by_type() { echo ''; }
            uci_get_by_name() { [ "$2" = server ] && echo node.example; }
            uci_set_by_name() { echo "$3" > "$TEST_ROOT/cached"; }
            resolveip() { return 1; }
            curl() {
                printf '%s\n' "$@" > "$TEST_ROOT/curl-args"
                echo 198.18.0.1
            }
            get_host_ip node > "$TEST_ROOT/resolved"
        ''')
        args = (self.base / "curl-args").read_text().splitlines()
        self.assertIn("--connect-timeout", args)
        self.assertIn("--max-time", args)
        self.assertEqual((self.base / "resolved").read_text().strip(), "198.18.0.1")
        self.assertEqual((self.base / "cached").read_text().strip(), "198.18.0.1")

    def test_invalid_response_uses_valid_cache_without_committing_garbage(self):
        self.patched_sources()
        self.shell(r'''
            . "$SSR_INIT" || exit
            uci_get_by_type() { echo ''; }
            uci_get_by_name() {
                case "$2" in server) echo node.example;; ip) echo 192.0.2.9;; esac
            }
            uci_set_by_name() { echo bad > "$TEST_ROOT/committed"; }
            resolveip() { echo 999.1.1.1; }
            curl() { echo '<html>captive portal</html>'; }
            get_host_ip node > "$TEST_ROOT/resolved"
        ''')
        self.assertEqual((self.base / "resolved").read_text().strip(), "192.0.2.9")
        self.assertFalse((self.base / "committed").exists())

    def test_unresolvable_node_without_valid_cache_fails_explicitly(self):
        self.patched_sources()
        result = self.shell(r'''
            . "$SSR_INIT" || exit
            uci_get_by_type() { echo ''; }
            uci_get_by_name() { [ "$2" = server ] && echo node.example || echo ERROR; }
            uci_set_by_name() { touch "$TEST_ROOT/committed"; }
            resolveip() { return 1; }
            curl() { return 28; }
            get_host_ip node > "$TEST_ROOT/resolved"
        ''', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.base / "resolved").read_text(), "")
        self.assertFalse((self.base / "committed").exists())

    def test_preflight_failure_does_not_stop_running_service(self):
        result = self.shell(r'''
            ssrp_preflight() { return 27; }
            ssrp_stop() { touch "$TEST_ROOT/stopped"; }
            ssrp_start() { touch "$TEST_ROOT/started"; }
            ssrp_run_locked ssrp_restart_locked
        ''', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.base / "stopped").exists())
        self.assertFalse((self.base / "started").exists())
        self.assert_old_generation()

    def test_literal_ip_validation_rejects_broken_colon_edges(self):
        self.shell(r'''
            for address in 192.0.2.1 ::1 2001:db8::1 1:2:3:4:5:6:7:8 ::ffff:192.0.2.1; do
                ssrp_valid_ip "$address" || exit 1
            done
            for address in 999.1.1.1 1::2: :1::2 1:2:3 1:::2 1::2::3; do
                if ssrp_valid_ip "$address"; then exit 1; fi
            done
        ''')

    def test_uci_set_failure_is_not_masked_by_successful_commit(self):
        self.patched_sources()
        result = self.shell(r'''
            . "$SSR_INIT" || exit
            uci_get_by_name() { [ "$2" = server ] && echo 192.0.2.1 || echo ''; }
            uci() {
                case "$1" in set) return 42;; commit) touch "$TEST_ROOT/committed";; esac
            }
            get_host_ip node
        ''', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.base / "committed").exists())

    def test_real_start_rules_stops_on_resolution_failure(self):
        init, _ = self.patched_sources()
        init.write_text(init.read_text(encoding="utf-8").replace(
            "/usr/bin/ssr-rules", "test_apply_rules"), encoding="utf-8", newline="\n")
        result = self.shell(r'''
            . "$SSR_INIT" || exit
            uci_get_by_type() { echo ''; }
            get_host_ip() { return 17; }
            test_apply_rules() { touch "$TEST_ROOT/applied"; }
            start_rules
        ''', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.base / "applied").exists())

    def test_failed_replacement_attempts_cleanup_and_returns_failure(self):
        result = self.shell(r'''
            ssrp_preflight() { :; }
            ssrp_stop() { printf 'stop:%s\n' "${SSRP_KEEP_DNS:-0}" >> "$TEST_ROOT/order"; }
            ssrp_start() { echo start >> "$TEST_ROOT/order"; return 23; }
            ssrp_run_locked ssrp_restart_locked
        ''', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.base / "order").read_text().splitlines(),
                         ["stop:1", "start", "stop:0"])

    def test_failed_cleanup_still_attempts_dns_bundle_removal_and_restart(self):
        result = self.shell(r'''
            ssrp_preflight() { :; }
            ssrp_stop() { return 19; }
            ssrp_dnsmasq() { echo "$1" > "$TEST_ROOT/dns-recovery"; }
            ssrp_run_locked ssrp_restart_locked
        ''', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.published.exists())
        self.assertEqual((self.base / "dns-recovery").read_text().strip(), "restart")

    def test_real_stop_propagates_firewall_cleanup_failure_before_killing_cores(self):
        init, _ = self.patched_sources()
        init.write_text(init.read_text(encoding="utf-8").replace(
            "/usr/bin/ssr-rules", "test_apply_rules"), encoding="utf-8", newline="\n")
        for failed_action in ("-K", "-X", "-f"):
            with self.subTest(action=failed_action):
                self.env["FAILED_ACTION"] = failed_action
                result = self.shell(r'''
                    . "$SSR_INIT" || exit
                    check_run_environment() { HAS_IPSET=0; USE_TABLES=nftables; }
                    uci_get_by_type() {
                        case "$2" in old_global_server) echo old;; global_server) echo new;; esac
                    }
                    uci() { :; }
                    test_apply_rules() { [ "$1" != "$FAILED_ACTION" ]; }
                    PS=test_ps
                    test_ps() { :; }
                    kill() { :; }
                    sleep() { :; }
                    ssrp_dnsmasq() { :; }
                    del_cron() { :; }
                    killall() { touch "$TEST_ROOT/killed"; }
                    ssrp_stop
                ''', check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.base / "killed").exists())

    def test_no_main_node_still_resolves_and_validates_local_socks_config(self):
        init, _ = self.patched_sources()
        rules = self.base / "rules"
        rules.mkdir()
        (rules / "deny.list").write_text("")
        init.write_text(init.read_text(encoding="utf-8").replace(
            "/etc/ssrplus/", rules.as_posix() + "/"), encoding="utf-8", newline="\n")
        result = self.shell(r'''
            . "$SSR_INIT" || exit
            DNSMASQ_CONF_DIR="$TEST_ROOT/dnsmasq.d"
            TMP_DNSMASQ_PATH="$TEST_ROOT/dnsmasq-ssrplus.d"
            check_run_environment() { HAS_IPSET=0; USE_TABLES=nftables; }
            uci_get_by_type() {
                case "$1:$2" in
                    global:global_server) echo nil;;
                    socks5_proxy:enabled) echo 1;;
                    socks5_proxy:server) echo localnode;;
                    *) echo "${3:-0}";;
                esac
            }
            start_local() { echo '{broken' > "$local_config_file"; }
            get_host_ip() { echo "$1" >> "$TEST_ROOT/resolved-nodes"; echo 192.0.2.1; }
            jq() { touch "$TEST_ROOT/json-checked"; return 4; }
            ssrp_preflight
        ''', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((self.base / "json-checked").exists())
        self.assertEqual((self.base / "resolved-nodes").read_text().splitlines(), ["localnode"])
        self.assert_old_generation()
        self.assert_no_stage()

    def test_preflight_json_validator_rejection_precedes_disruptive_stop(self):
        init, _ = self.patched_sources()
        text = init.read_text(encoding="utf-8").replace(
            "/usr/share/shadowsocksr/gfw2ipset.sh", "test_gfw_generator")
        init.write_text(text, encoding="utf-8", newline="\n")
        result = self.shell(r'''
            . "$SSR_INIT" || exit
            DNSMASQ_CONF_DIR="$TEST_ROOT/dnsmasq.d"
            TMP_DNSMASQ_PATH="$TEST_ROOT/dnsmasq-ssrplus.d"
            TMP_PATH="$TEST_ROOT/service"
            LOCK_FILE="$TEST_ROOT/lifecycle.lock"
            check_run_environment() { HAS_IPSET=0; USE_TABLES=nftables; }
            load_config() { GLOBAL_SERVER=node; return 0; }
            get_host_ip() { echo 192.0.2.1; }
            Start_Run() { echo '{broken' > "$TMP_PATH/tcp-only-ssr-retcp.json"; }
            start_dns() { :; }
            test_gfw_generator() { echo 'server=/ok.example/192.0.2.1' > "$SSRP_DNS_STAGE/gfw.conf"; }
            jq() { return 4; }
            ssrp_stop() { touch "$TEST_ROOT/stopped"; }
            ssrp_start() { touch "$TEST_ROOT/started"; }
            ssrp_run_locked ssrp_restart_locked
        ''', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.base / "stopped").exists())
        self.assertFalse((self.base / "started").exists())
        self.assert_old_generation()
        self.assert_no_stage()


if __name__ == "__main__":
    unittest.main()
