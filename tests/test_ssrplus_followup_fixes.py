#!/usr/bin/env python3
# Historical 190-r12 regression only; production v198.2 coverage is test_ssrplus_v198.py.
"""Run the actual ordered SSR patches against the immutable upstream files.

The tests replace only unavailable OS commands and fixed filesystem paths. They
exercise the imported init functions, including start_rules/start_dns ordering;
they do not implement their own resolver or custom-port selection logic.
"""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
BASH = os.environ.get("BASH") or (
    "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash"))
FOLLOWUPS = {"ssrplus-dns-forwarding.patch", "ssrplus-custom-ports.patch"}


@unittest.skipUnless(BASH, "Bash is required to execute the patched init")
class FollowupFixes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prepared = tempfile.TemporaryDirectory(prefix="ssrp-followup-source-")
        cls.addClassCleanup(cls.prepared.cleanup)
        cls.package = Path(cls.prepared.name)
        cls.environment = os.environ.copy()
        cls.environment["MSYS_NO_PATHCONV"] = "1"
        for entry in (ROOT / "tests/fixtures/ssrplus-legacy/wrt_core/compat/ssrplus/source-files.tsv").read_text().splitlines():
            blob, target, fixture = entry.split()
            data = (ROOT / "tests/fixtures" / fixture).read_bytes()
            actual = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            if actual != blob:
                raise AssertionError("upstream fixture changed: " + fixture)
            destination = cls.package / target
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
        subprocess.run(["git", "init", "-q", str(cls.package)], check=True,
                       capture_output=True, env=cls.environment)
        for name in (ROOT / "tests/fixtures/ssrplus-legacy/wrt_core/compat/ssrplus/patches.list").read_text().splitlines():
            if os.environ.get("SSR_FOLLOWUPS_UNPATCHED") and name in FOLLOWUPS:
                continue
            result = subprocess.run(["git", "-C", str(cls.package), "apply",
                                     str(ROOT / "tests/fixtures/ssrplus-legacy/wrt_core/patches" / name)],
                                    text=True, capture_output=True, env=cls.environment)
            if result.returncode:
                raise AssertionError("ordered patch failed: " + name + "\n" + result.stderr)
        cls.init_code = (cls.package / "root/etc/init.d/shadowsocksr").read_text(encoding="utf-8")

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="ssrp-followup-run-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.environment = self.environment.copy()
        self.environment["TEST_ROOT"] = self.base.as_posix()
        self.init = self.base / "init.sh"
        code = self.init_code.replace(
            '${IPKG_INSTROOT:-}/usr/share/shadowsocksr/ssrp-runtime.sh',
            (ROOT / "tests/fixtures/ssrplus-legacy/wrt_core/compat/ssrplus/runtime.sh").as_posix())
        code = code.replace("/usr/bin/ssr-rules", self.base.as_posix() + "/ssr-rules")
        code = code.replace("/usr/share/shadowsocksr/gfw2ipset.sh", "/bin/true")
        code = code.replace("/etc/ssrplus/mosdns-config.yaml", self.base.as_posix() + "/mosdns.yaml")
        code = code.replace("mkdir -p /var/run /var/lock /var/log", "mkdir -p \"$TEST_ROOT/run\"")
        self.init.write_text(code, encoding="utf-8", newline="\n")
        (self.base / "mosdns.yaml").write_text("\n" * 16, newline="\n")
        command = self.base / "ssr-rules"
        command.write_text('''#!/bin/sh
printf 'rules:%s\\n' "$*" >> "$TEST_ROOT/events"
printf '%s\\n' "$@" > "$TEST_ROOT/rule-args"
case "$1" in
    -P) cp "$TEST_ROOT/elements" "$TEST_ROOT/snapshot" ;;
    *) touch "$TEST_ROOT/live-set" ;;
esac
''', encoding="utf-8", newline="\n")
        command.chmod(0o755)
        self.preamble = r'''
source "$TEST_ROOT/init.sh"
USE_TABLES=nftables HAS_IPSET=0
TEST_MODE=gfw TEST_DPORTS=1 TEST_DNS=1 TEST_RESOLVER=8.8.4.4:53
GLOBAL_SERVER=node-a UDP_RELAY_SERVER=nil SHUNT_SERVER=nil shunt=0
TMP_PATH="$TEST_ROOT" TMP_BIN_PATH="$TEST_ROOT/bin"
TMP_DNSMASQ_PATH="$TEST_ROOT" DNSMASQ_CONF_DIR="$TEST_ROOT"
touch "$TEST_ROOT/elements"
uci_get_by_type() {
    case "$1:$2" in
        global:run_mode) echo "$TEST_MODE" ;;
        global:dports) echo "$TEST_DPORTS" ;;
        global:custom_ports) echo "${TEST_CUSTOM_PORTS-80,443,1000:2000}" ;;
        global:pdnsd_enable) echo "$TEST_DNS" ;;
        global:parse_method) echo '' ;;
        global:tunnel_forward|global:tunnel_forward_mosdns) echo "$TEST_RESOLVER" ;;
        global:apple_optimization|global:netflix_enable|global:adblock) echo 0 ;;
        global:global_server) echo node-a ;;
        *) printf '%s\n' "$3" ;;
    esac
}
uci_get_by_name() {
    case "$2" in local_port) echo 1234 ;; custom_ports) echo 9999 ;; esac
}
get_host_ip() { echo 192.0.2.1; }
ln_start_bin() { :; }
first_type() { echo /bin/true; }
echolog() { :; }
uci() { :; }
nft() {
    printf 'nft:%s\n' "$*" >> "$TEST_ROOT/events"
    case "$*" in
        'list set inet ss_spec gfwlist')
            [ -f "$TEST_ROOT/live-set" ] || return 1
            printf 'table inet ss_spec { set gfwlist { type ipv4_addr; } }\n' ;;
        'add element inet ss_spec gfwlist '* )
            [ -f "$TEST_ROOT/live-set" ] || return 90
            [ ! -f "$TEST_ROOT/fail-add" ] || return 92
            printf '%s\n' "$*" >> "$TEST_ROOT/elements" ;;
        *) return 91 ;;
    esac
}
ipset() { printf 'ipset:%s\n' "$*" >> "$TEST_ROOT/events"; }
'''

    def shell(self, body):
        result = subprocess.run([BASH, "--noprofile", "--norc", "-c", self.preamble + body],
                                env=self.environment, text=True, encoding="utf-8",
                                capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def events(self):
        path = self.base / "events"
        return path.read_text().splitlines() if path.exists() else []

    def test_nft_gfw_dns_is_forwarded_without_ipset_installed(self):
        self.shell('touch "$TEST_ROOT/live-set"; start_dns')
        self.assertEqual((self.base / "elements").read_text().splitlines(),
                         ["add element inet ss_spec gfwlist { 8.8.4.4 }"])

    def test_prepare_only_never_queries_or_mutates_live_firewall(self):
        self.shell(r'''
touch "$TEST_ROOT/live-set"
SSRP_PREPARE_ONLY=1 HAS_IPSET=1
start_dns
add_dns_into_ipset gfw 8.8.8.8:53
''')
        self.assertEqual(self.events(), [])

    def test_nft_other_modes_do_not_use_ipset_or_add_gfw_entries(self):
        self.shell(r'''
touch "$TEST_ROOT/live-set"
HAS_IPSET=1
for TEST_MODE in router all oversea; do start_dns || exit; done
''')
        self.assertEqual(self.events(), [])

    def test_missing_live_set_never_gets_an_element_or_table_created(self):
        self.shell('start_dns')
        self.assertEqual((self.base / "elements").read_text(), "")
        self.assertTrue(all(event == "nft:list set inet ss_spec gfwlist"
                            for event in self.events()), self.events())

    def test_ipv6_and_invalid_resolvers_do_not_enter_ipv4_sets(self):
        self.shell(r'''
touch "$TEST_ROOT/live-set"
HAS_IPSET=1
for TEST_RESOLVER in '[2001:4860:4860::8888]:53' '2001:4860:4860::8888' \
    'tls://[2001:4860:4860::8888]:853' '999.1.1.1:53' 'dns.example:53' \
    '1.2.3.4;flush:53'; do
    start_dns || exit
done
''')
        self.assertEqual((self.base / "elements").read_text(), "")
        self.assertFalse(any(event.startswith("ipset:") or "add element" in event
                             for event in self.events()), self.events())

    def test_mosdns_inserts_each_ipv4_resolver_and_skips_ipv6(self):
        self.shell(r'''
touch "$TEST_ROOT/live-set"
TEST_DNS=4 TEST_RESOLVER='tls://1.1.1.1:853,8.8.8.8:53,[2001:4860:4860::8888]:53'
start_dns
''')
        self.assertEqual((self.base / "elements").read_text().splitlines(), [
            "add element inet ss_spec gfwlist { 1.1.1.1 }",
            "add element inet ss_spec gfwlist { 8.8.8.8 }"])

    def test_failed_live_nft_insertion_stops_dns_activation(self):
        self.shell(r'''
touch "$TEST_ROOT/live-set" "$TEST_ROOT/fail-add"
if start_dns; then exit 11; fi
''')
        self.assertEqual((self.base / "elements").read_text(), "")

    def test_global_custom_ports_reach_the_actual_rule_command(self):
        self.shell('TEST_DPORTS=3; start_rules')
        args = (self.base / "rule-args").read_text().splitlines()
        self.assertEqual(args[args.index("-D") + 1], "-m multiport --dports 80,443,1000:2000")

    def test_all_ports_and_empty_custom_value_do_not_reuse_node_ports(self):
        for mode in ("1", "3"):
            with self.subTest(mode=mode):
                self.shell(f'TEST_DPORTS={mode} TEST_CUSTOM_PORTS=; start_rules')
                args = (self.base / "rule-args").read_text().splitlines()
                self.assertEqual(args[args.index("-D") + 1], "")

    def test_standard_port_preset_is_preserved(self):
        self.shell('TEST_DPORTS=2; start_rules')
        args = (self.base / "rule-args").read_text().splitlines()
        self.assertEqual(args[args.index("-D") + 1],
                         "-m multiport --dports 22,53,587,465,995,993,143,80,443,853,9418")

    def test_iptables_dns_behavior_is_preserved(self):
        self.shell(r'''
USE_TABLES=iptables HAS_IPSET=1
for TEST_MODE in gfw oversea router; do start_dns || exit; done
''')
        self.assertEqual(self.events(), ["ipset:add gfwlist 8.8.4.4",
                                        "ipset:add oversea 8.8.4.4",
                                        "ipset:add ss_spec_wan_ac 8.8.4.4 nomatch"])

    def test_existing_iptables_member_does_not_abort_dns_start(self):
        self.shell(r'''
USE_TABLES=iptables HAS_IPSET=1
ipset() { return 1; }
start_dns
''')

    def test_start_activates_rules_then_dns_then_updates_private_snapshot(self):
        self.shell(r'''
ssrp_dns_begin() { :; }
check_run_environment() { :; }
check_server() { :; }
load_config() { return 0; }
Start_Run() { :; }
start_xhttp_addr() { :; }
add_cron() { :; }
start_switch() { :; }
ssrp_dns_publish() { printf 'publish\n' >> "$TEST_ROOT/events"; }
ssrp_dnsmasq() { :; }
start_server() { :; }
start_monitor() { :; }
clean_log() { :; }
ssrp_start
''')
        events = self.events()
        insertion = "nft:add element inet ss_spec gfwlist { 8.8.4.4 }"
        self.assertIn(insertion, events)
        self.assertLess(next(index for index, event in enumerate(events)
                             if event.startswith("rules:-s")), events.index(insertion))
        self.assertIn("rules:-P", events)
        self.assertLess(events.index(insertion), events.index("rules:-P"))
        self.assertLess(events.index("rules:-P"), events.index("publish"))
        self.assertEqual((self.base / "snapshot").read_text().splitlines(),
                         ["add element inet ss_spec gfwlist { 8.8.4.4 }"])


if __name__ == "__main__":
    unittest.main()
