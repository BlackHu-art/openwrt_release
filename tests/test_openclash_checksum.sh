#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
BASE_PATH="$repo_root/wrt_core"
source "$BASE_PATH/modules/plugin_compat.sh"
fixtures="$repo_root/tests/fixtures/plugin-runtime"
temp_base=$(cd "${TMPDIR:-/tmp}" && pwd -P)
test_root=$(mktemp -d "$temp_base/openclash-checksum.XXXXXX")
cleanup() {
    case "$test_root" in
        "$temp_base"/openclash-checksum.*)
            [[ -n "$test_root" && "$test_root" != "$temp_base" ]] && rm -rf -- "$test_root"
            ;;
        *) echo "Refusing to remove unexpected test directory: $test_root" >&2 ;;
    esac
}
trap cleanup EXIT
fail() { echo "FAIL: $*" >&2; exit 1; }

make_package() {
    local package=$1
    python "$repo_root/tests/openclash_fixture.py" "$package"
}

snapshot() {
    (
        cd "$1"
        find . -path './.git' -prune -o -type f -print | LC_ALL=C sort |
            while IFS= read -r path; do sha256sum "$path"; done
    )
}

# Exercise the sparse-feed layout used by the production build helper.
git init -q "$test_root"
git -C "$test_root" config core.autocrlf false
package="$test_root/package"
make_package "$package"
fix_openclash_compat "$package"
source "$package/root/usr/share/openclash/openclash_curl.sh"

# Keep the production SHA calculation and parser; isolate only remote I/O/logging.
DEFAULT_UA=test
curl() { cat "$test_root/checksums"; }
LOG_WARN() { printf 'WARN:%s\n' "$*"; }
LOG_OUT() { printf 'OUT:%s\n' "$*"; }
LOG_ERROR() { printf 'ERROR:%s\n' "$*"; }
printf abc > "$test_root/core"
# Standard SHA-256 test vector for the literal bytes "abc".
good_sha=ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad
bad_sha=0000000000000000000000000000000000000000000000000000000000000000
name=clash-linux-arm64.tar.gz
cases=0
failures=0
checksum_case() {
    local description=$1 expected_name=$2 expected_rc=$3 level=$4 manifest=$5 rc=0
    cases=$((cases + 1))
    printf '%s\n' "$manifest" > "$test_root/checksums"
    verify_sha256_checksum "$test_root/core" "$expected_name" fixture > "$test_root/case.log" 2>&1 || rc=$?
    if [[ $rc != "$expected_rc" ]] ||
        [[ $(cut -d: -f1 "$test_root/case.log") != "$level" ]]; then
        echo "FAIL: $description (exit $rc; expected $expected_rc and $level)" >&2
        cat "$test_root/case.log" >&2
        failures=$((failures + 1))
    fi
}

checksum_case 'exact checksum succeeds' "$name" 0 OUT "$good_sha  $name"
checksum_case 'prefix collision selects the exact filename' "$name" 0 OUT \
    "$(printf '%s  %s\n%s  %s\n' "$bad_sha" "old-$name" "$good_sha" "$name")"
checksum_case 'suffix collision selects the exact filename' "$name" 0 OUT \
    "$(printf '%s  %s\n%s  %s\n' "$bad_sha" "$name.old" "$good_sha" "$name")"
checksum_case 'prefix-only entry preserves warning and skip' "$name" 0 WARN "$bad_sha  old-$name"
checksum_case 'binary marker without a directory succeeds' "$name" 0 OUT "$good_sha  *$name"
checksum_case 'uppercase SHA with binary marker, path and CRLF succeeds' "$name" 0 OUT \
    "$(printf '%s  *./releases/%s\r\n' "${good_sha^^}" "$name")"
checksum_case 'literal regex characters select the exact filename' 'clash-linux-[arm64].tar.gz' 0 OUT \
    "$(printf '%s  %s\n%s  %s\n' "$bad_sha" 'clash-linux-aXtarYgz' "$good_sha" 'clash-linux-[arm64].tar.gz')"
checksum_case 'genuine checksum mismatch fails' "$name" 1 ERROR "$bad_sha  $name"
checksum_case 'missing filename preserves warning and skip' "$name" 0 WARN "$good_sha  other.tar.gz"
checksum_case 'empty manifest preserves warning and skip' "$name" 0 WARN ''
checksum_case 'missing hash preserves warning and skip' "$name" 0 WARN "  $name"
checksum_case 'short hash preserves warning and skip' "$name" 0 WARN "${good_sha:1}  $name"
checksum_case 'long hash preserves warning and skip' "$name" 0 WARN "${good_sha}0  $name"
checksum_case 'nonhex hash preserves warning and skip' "$name" 0 WARN "${good_sha%?}G  $name"
checksum_case 'empty expected filename skips verification' '' 0 '' "$good_sha  $name"

# The whole production patch group must be idempotent, including WAN subnets.
snapshot "$package" > "$test_root/before"
fix_openclash_compat "$package" > "$test_root/repeat.log"
snapshot "$package" > "$test_root/after"
cmp "$test_root/before" "$test_root/after" || fail 'repeated application changed source bytes'

# A checksum source drift must reject the whole group before applying WAN changes.
unknown_package="$test_root/unknown"
make_package "$unknown_package"
printf '%s\n' 'unrecognized replacement source' > "$unknown_package/root/usr/share/openclash/openclash_curl.sh"
snapshot "$unknown_package" > "$test_root/before"
if fix_openclash_compat "$unknown_package" > "$test_root/reject.log" 2>&1; then
    fail 'unknown checksum source was accepted'
fi
snapshot "$unknown_package" > "$test_root/after"
cmp "$test_root/before" "$test_root/after" || fail 'rejected source was partially changed'
[[ -z $(find "$unknown_package" -name '*.rej' -o -name '*.orig') ]] || fail 'rejection left patch artifacts'

[[ $failures -eq 0 ]] || fail "$failures of $cases checksum cases failed"
echo "OpenClash checksum behavior: PASS ($cases cases; idempotence and source guard)"
