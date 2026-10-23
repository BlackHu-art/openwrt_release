#!/usr/bin/env bash
set -euo pipefail
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
BASE_PATH="$repo_root/wrt_core"
if [[ ${PLUGIN_FIX_MODE:-fixed} != original ]]; then
    source "$BASE_PATH/modules/plugin_compat.sh"
fi
fixtures="$repo_root/tests/fixtures/plugin-runtime"
temp_base=$(cd "${TMPDIR:-/tmp}" && pwd -P)
test_root=$(mktemp -d "$temp_base/plugin-runtime.XXXXXX")
cleanup() {
    case "$test_root" in
        "$temp_base"/plugin-runtime.*) rm -rf -- "$test_root" ;;
        *) echo "Unexpected test path: $test_root" >&2 ;;
    esac
}
trap cleanup EXIT
fail() { echo "FAIL: $*" >&2; exit 1; }
snapshot() {
    (cd "$1"; find . -path './.git' -prune -o -type f -print |
        LC_ALL=C sort | while read -r path; do sha256sum "$path"; done)
}
verify_patch_contract() {
    local package=$1 fixer=$2 drift_file=$3
    snapshot "$package" > "$test_root/before"
    "$fixer" "$package" > "$test_root/repeat.log"
    snapshot "$package" > "$test_root/after"
    cmp "$test_root/before" "$test_root/after" || fail "$fixer is not idempotent"
    # A partial/rebased upstream fix must be rejected before touching other files.
    printf '%s\n' 'unrecognized replacement source' > "$drift_file"
    snapshot "$package" > "$test_root/before"
    if "$fixer" "$package" > "$test_root/rejection.log" 2>&1; then
        fail "$fixer accepted incompatible source"
    fi
    snapshot "$package" > "$test_root/after"
    cmp "$test_root/before" "$test_root/after" || fail "$fixer partially modified source"
}

test_adguard() {
    local package="$test_root/adguard"
    mkdir -p "$package/root/usr/share/AdGuardHome" "$package/luasrc/controller"
    cp "$fixtures/adguard-updater.sh" "$package/root/usr/share/AdGuardHome/update_core.sh"
    cp "$fixtures/adguard-links.txt" "$package/root/usr/share/AdGuardHome/links.txt"
    cp "$fixtures/AdGuardHome.lua" "$package/luasrc/controller/AdGuardHome.lua"
    git init -q "$package"
    git -C "$package" config core.autocrlf false
    if [[ ${PLUGIN_FIX_MODE:-fixed} != original ]]; then
        fix_adguardhome_compat "$package"
    fi
    local updater="$package/root/usr/share/AdGuardHome/update_core.sh"
    # Only evaluate functions: no UCI commands, downloads or service restarts.
    eval "$(sed -n '/^core_version()/,/^}/p; /^version_is_newer()/,/^}/p; /^check_latest_version()/,/^}/p' "$updater")"
    check_wgetcurl() { downloader=fake_download; }
    fake_download() { printf '{"tag_name":"%s"}\n' "$REMOTE_VERSION"; }
    fake_binary() { printf 'AdGuard Home version %s\n' "$LOCAL_VERSION"; }
    doupdate_core() { touch "$test_root/updated"; }
    EXIT() { exit "$1"; }
    version_case() {
        local current=$1 remote=$2 mode=$3 expected=$4 expected_rc=${5:-0} rc=0
        rm -f "$test_root/updated"
        (
            set +e
            LOCAL_VERSION=$current REMOTE_VERSION=$remote
            binpath=fake_binary upxflag=''
            check_latest_version "$mode"
        ) > "$test_root/version.log" 2>&1 || rc=$?
        [[ $rc == "$expected_rc" ]] || fail "version check $current -> $remote returned $rc"
        local updated=no
        [[ ! -e "$test_root/updated" ]] || updated=yes
        [[ $updated == "$expected" ]] || fail "update decision $current -> $remote ($mode): $updated"
    }
    version_case v1.0.0-b.1 v0.107.79 '' no
    version_case v1.0.0-b.1 v1.0.0 '' yes
    version_case v1.1.0-b.1+build v1.0.0 '' no
    version_case v0.107.80 v0.107.79 '' no
    version_case v0.107.79 v0.107.79 '' no
    version_case v0.107.9 v0.107.79 '' yes
    version_case v0.107.79 v0.108.0 '' yes
    version_case '' v0.107.79 '' yes
    version_case v1.0.0 v0.107.79 force yes
    version_case v0.107.79 '' '' no 1
    version_case v0.107.79 v1.0.0-b.1 '' no 1
    if [[ ${PLUGIN_FIX_MODE:-fixed} != original ]]; then
        verify_patch_contract "$package" fix_adguardhome_compat "$updater"
    fi
    echo "AdGuard Home update behavior: PASS"
}

test_openclash() {
    local package="$test_root/openclash"
    python "$repo_root/tests/openclash_fixture.py" "$package"
    # Sparse feed transfer removes the package's own .git directory in production.
    git init -q "$test_root"
    git -C "$test_root" config core.autocrlf false
    if [[ ${PLUGIN_FIX_MODE:-fixed} != original ]]; then
        fix_openclash_compat "$package"
    fi
    source "$package/root/usr/share/openclash/openclash_curl.sh"
    DEFAULT_UA=test
    LOG_WARN() { :; }
    LOG_OUT() { :; }
    LOG_ERROR() { :; }
    curl() { cat "$test_root/checksums"; }
    printf 'firmware core\n' > "$test_root/core"
    local actual_hash
    actual_hash=$(sha256sum "$test_root/core" | awk '{print $1}')
    printf '%s  %s\n%s  %s\n' \
        badhash 'clash-linux-arm64XtarYgz' "$actual_hash" 'clash-linux-arm64.tar.gz' \
        > "$test_root/checksums"
    verify_sha256_checksum "$test_root/core" 'clash-linux-arm64.tar.gz' fixture ||
        fail "checksum lookup treated dots in the filename as regular expressions"
    printf 'corrupted\n' > "$test_root/core"
    if verify_sha256_checksum "$test_root/core" 'clash-linux-arm64.tar.gz' fixture; then
        fail "corrupt download passed checksum verification"
    fi

    nft() { printf 'nft %s\n' "$*" >> "$test_root/network.log"; }
    ipset() { printf 'ipset %s\n' "$*" >> "$test_root/network.log"; }
    local wan_ip4s='198.51.100.2' lan_ip4s='198.51.100.0/24 203.0.113.0/24'
    # Run the original source's two startup-set sections with command recorders.
    eval "$(sed -n '/^   if \[ -n "\$wan_ip4s" \]; then/,/^   #common ports/p' "$package/root/etc/init.d/openclash")"
    for subnet in $lan_ip4s; do
        grep -Fxq "nft add element inet fw4 localnetwork { $subnet }" "$test_root/network.log" ||
            fail "nft startup omitted WAN subnet $subnet"
        grep -Fxq "ipset add localnetwork $subnet" "$test_root/network.log" ||
            fail "ipset startup omitted WAN subnet $subnet"
    done
    if [[ ${PLUGIN_FIX_MODE:-fixed} != original ]]; then
        verify_patch_contract "$package" fix_openclash_compat "$package/root/usr/share/openclash/openclash_curl.sh"
    fi
    echo "OpenClash checksum and startup network behavior: PASS"
}

case ${1:-all} in
    adguard) test_adguard ;;
    openclash) test_openclash ;;
    all) test_adguard; test_openclash ;;
    *) fail "unknown test group: $1" ;;
esac
