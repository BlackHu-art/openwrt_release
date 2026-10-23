#!/usr/bin/env bash
set -euo pipefail
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
BASE_PATH="$repo_root/wrt_core"
source "$BASE_PATH/modules/feed_source_fixes.sh"
source "$BASE_PATH/modules/plugin_compat.sh"
temp_base=$(cd "${TMPDIR:-/tmp}" && pwd -P)
test_root=$(mktemp -d "$temp_base/homeproxy-routing.XXXXXX")
cleanup() {
    case "$test_root" in
        "$temp_base"/homeproxy-routing.*) rm -rf -- "$test_root" ;;
        *) echo "Unexpected test path: $test_root" >&2 ;;
    esac
}
trap cleanup EXIT
mkdir -p "$test_root/root/etc/init.d" "$test_root/root/etc/homeproxy/scripts" \
    "$test_root/root/usr/share/rpcd/ucode" "$test_root/htdocs/luci-static/resources/view/homeproxy"
fixtures="$repo_root/tests/fixtures/homeproxy"
cp "$fixtures/Makefile" "$test_root/"
cp "$fixtures/homeproxy.init" "$test_root/root/etc/init.d/homeproxy"
cp "$fixtures/luci.homeproxy" "$test_root/root/usr/share/rpcd/ucode/luci.homeproxy"
cp "$fixtures/fadaa676/generate_client.uc" "$test_root/root/etc/homeproxy/scripts/"
cp "$fixtures/fadaa676/client.js" "$test_root/htdocs/luci-static/resources/view/homeproxy/"
git init -q "$test_root"
git -C "$test_root" config core.autocrlf false
fix_homeproxy_compat "$test_root" > "$test_root/patch.log"
init="$test_root/root/etc/init.d/homeproxy"

# Exercise the real routing sections; do not run host service/network commands.
eval "$(sed -n '/^clear_policy_rule() {/,/^}/p' "$init")"
setup_routes() {
    eval "$(sed -n '/# Setup routing table/,/# sing-box (client)/p' "$init")"
}
clear_routes() {
    eval "$(sed -n '/^[[:space:]]*# Tproxy$/,/^[[:space:]]*# Nftables rules$/p' "$init")"
}
clear_chains() {
    eval "$(sed -n '/^[[:space:]]*# Nftables rules$/,/done 2>/p' "$init")"
}
fail() { echo "FAIL: $*" >&2; exit 1; }
config_get() { printf -v "$1" '%s' "${4:-}"; }
sleep() { :; }
nft() { printf '%s\n' "$*" >> "$test_root/nft.log"; }
declare -A rules=() routes=()
ip() {
    local family=4 key action
    if [[ $1 == -6 ]]; then family=6; shift; fi
    case "$1" in
        rule)
            action=$2
            key="$family:$4:$6"
            if [[ $action == add ]]; then
                rules[$key]=$(( ${rules[$key]:-0} + 1 ))
            elif (( ${rules[$key]:-0} > 0 )); then
                rules[$key]=$(( ${rules[$key]} - 1 ))
            else
                return 1
            fi
            ;;
        route)
            action=$2
            shift 2
            key="$family:$*"
            case "$action" in
                add)
                    [[ ${routes[$key]:-0} == 0 ]] || fail "duplicate route add: $key"
                    routes[$key]=1 ;;
                replace) routes[$key]=1 ;;
                del) unset 'routes[$key]' ;;
            esac
            ;;
        tuntap|link) : ;;
        *) fail "unexpected ip command: $*" ;;
    esac
}

table_mark=100 tproxy_mark=101 tun_mark=102 tun_name=singtun0
routing_mode=custom ipv6_support=1
for proxy_mode in redirect_tproxy redirect_tun tun; do
    rules=([4:101:100]=3 [6:101:100]=3 [4:102:100]=3 [6:102:100]=3 [4:999:200]=2)
    routes=()
    setup_routes
    setup_routes
    mark=102
    [[ $proxy_mode != redirect_tproxy ]] || mark=101
    for family in 4 6; do
        [[ ${rules[$family:$mark:100]} == 1 ]] || fail "$proxy_mode accumulated IPv$family rules"
    done
    clear_routes
    clear_routes
    for key in 4:101:100 6:101:100 4:102:100 6:102:100; do
        [[ ${rules[$key]} == 0 ]] || fail "stop left rules: $key"
    done
    [[ ${rules[4:999:200]} == 2 ]] || fail "unrelated policy rules were removed"
done
clear_chains
grep -Fxq 'delete chain inet fw4 homeproxy_mangle_lanac' "$test_root/nft.log" ||
    fail "the LAN access chain was not cleaned"
echo "HomeProxy routing cleanup behavior: PASS"
