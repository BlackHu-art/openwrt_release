#!/usr/bin/env bash
# Current v198.2 kernel/parser gate, exclusively inside a fresh network namespace.
set -eo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
fail() { echo "FAIL: $*" >&2; exit 1; }
[[ $(uname -s) == Linux ]] || fail 'Linux is required'
[[ $EUID == 0 ]] || fail 'run with sudo unshare -n'
[[ $(readlink /proc/self/ns/net) != "$(readlink /proc/1/ns/net)" ]] ||
    fail 'refusing firewall operations outside a separate network namespace'
for tool in nft ip dnsmasq python3; do command -v "$tool" >/dev/null || fail "missing $tool"; done
temporary=$(mktemp -d)
trap 'rm -rf -- "$temporary"' EXIT
python3 tests/prepare_ssrplus_candidate.py --output "$temporary/package"

# Use the actual prepared IPv6 implementation. Only bridge sysctl/save-file
# access is omitted: this gate exercises nft/IP policy routing, not host knobs.
source "$temporary/package/root/usr/share/shadowsocksr/ipv6.sh"
ipv6_bridge_nf() { :; }
uci_get_by_type() { echo fixture; }
uci_get_by_name() { echo 2001:db8::123; }
ip link set lo up
nft 'add table inet fw4'
nft 'add chain inet fw4 retained { type filter hook input priority filter; policy accept; }'
nft list table inet fw4 > "$temporary/fw4.before"
FWMARK=0x53535250
WAN_BP_IP='2001:db8:1::/48' WAN_FW_IP='2001:db8:2::/48'
LAN_FP_IP='2001:db8:3::/64' LAN_BP_IP='2001:db8:4::/64' LAN_GM_IP='2001:db8:5::/64'
LAN_AC_IP='w2001:db8:6::/64' Interface='' PROXY_PORTS='80,443' TPROXY=1
local_port=1234 LOCAL_PORT=1235 DISABLE_UDP_RULES=0
for RUNMODE in gfw router all; do
    for OUTPUT in 0 1 2; do
        nft 'add table inet ss_spec'
        ipv6_rules_generate > "$temporary/current.nft"
        nft -c -f "$temporary/current.nft"
        nft -f "$temporary/current.nft"
        nft list chain inet ss_spec ss_spec6_redirect | grep -q 'redirect to :1234'
        nft list chain inet ss_spec ss_spec6_udp_proxy | grep -q 'tproxy ip6 to :1235'
        ipv6_policy_route
        ipv6_policy_route
        [[ $(ip -6 rule show | grep -c 'fwmark 0x53535250.*lookup 999') == 1 ]]
        ip -6 route show table 999 | grep -q 'local.*dev lo'
        ipv6_policy_cleanup
        ! ip -6 rule show | grep -q 'fwmark 0x53535250.*lookup 999'
        nft delete table inet ss_spec
        nft list table inet fw4 > "$temporary/fw4.after"
        cmp "$temporary/fw4.before" "$temporary/fw4.after"
    done
done
echo 'Current fw876 IPv6 rules: 9 modes accepted; policy routes cleaned; fw4 retained: PASS'

# Generate the upstream router-mode DNS fragment through the full init program.
# Router-facing UCI, executable lookup and launches are isolated by the same
# current-source harness used by unit tests; dnsmasq parsing itself is real.
python3 - "$temporary/dns.conf" <<'PY'
from pathlib import Path
import sys
sys.path.insert(0, 'tests')
from test_ssrplus_v198 import UpstreamRuntime
case = UpstreamRuntime()
try:
    case.setUp()
    result = case.shell('''
mkdir -p "$TMP_DNSMASQ_PATH"
normalize_run_mode() { echo router; }
ifstatus() { echo '{}'; }
jsonfilter() { echo 119.29.29.29; }
uci_get_by_type() {
    case "$2" in
        pdnsd_enable) echo 1 ;; ipv6_support) echo 1 ;;
        global_server) echo node ;; chinadns_forward) echo 223.5.5.5 ;;
        apple_optimization) echo 0 ;; *) printf '%s\\n' "$3" ;;
    esac
}
start_dns
''')
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    fragments = list((case.base / 'dnsmasq-ssrplus.d').glob('*.conf'))
    if not fragments:
        raise AssertionError('upstream router mode emitted no DNS fragment')
    content = '\n'.join(path.read_text() for path in fragments)
    if 'server=127.0.0.1#5333' not in content:
        raise AssertionError('router DNS forwarding not exercised')
    Path(sys.argv[1]).write_text(content)
finally:
    case.doCleanups()
PY
dnsmasq --test --conf-file="$temporary/dns.conf"
echo 'Current fw876 router DNS fragment accepted by real dnsmasq: PASS'
