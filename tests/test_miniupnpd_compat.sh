#!/usr/bin/env bash
set -euo pipefail
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
BASE_PATH="$repo_root/wrt_core"
source "$BASE_PATH/modules/target_fixes.sh"
test_root=$(mktemp -d "${TMPDIR:-/tmp}/miniupnpd-compat.XXXXXX")
trap 'rm -rf -- "$test_root"' EXIT
BUILD_DIR="$test_root/build"
package="$BUILD_DIR/feeds/packages/net/miniupnpd"
fixture="$repo_root/tests/fixtures/miniupnpd"

reset_package() {
    mkdir -p "$package/patches"
    cp "$fixture/"*.patch "$package/patches/"
    printf 'PKG_VERSION:=%s\n' "$1" > "$package/Makefile"
}
snapshot() {
    (cd "$package"; find . -type f -print0 | sort -z | xargs -0 sha256sum)
}
reset_package 2.3.11
fix_miniupnpd
[[ ! -e "$package/patches/020-descr-filter-fix.patch" ]]
[[ ! -e "$package/patches/030-allow-private-fix.patch" ]]
cmp "$package/patches/040-improve-logging.patch" "$BASE_PATH/patches/miniupnpd-2.3.11-improve-logging.patch"
cmp "$package/patches/999-chanage-default-leaseduration.patch" "$BASE_PATH/patches/999-chanage-default-leaseduration.patch"
before=$(snapshot)
fix_miniupnpd
[[ "$(snapshot)" == "$before" ]]

# Other versions must retain their own patch stack, including later upstream fixes.
for version in 2.3.9 2.3.12; do
    reset_package "$version"
    before=$(snapshot)
    fix_miniupnpd_2311_patches "$package"
    [[ "$(snapshot)" == "$before" ]]
done

# Validate the whole stack before removing the first obsolete patch.
reset_package 2.3.11
printf '\nupstream drift\n' >> "$package/patches/040-improve-logging.patch"
before=$(snapshot)
if fix_miniupnpd; then
    echo 'FAIL: unexpected patch content was accepted' >&2
    exit 1
fi
[[ "$(snapshot)" == "$before" ]]

# OpenWrt or an upstream fix may already have removed all three patches.
rm -f "$package/patches/020-descr-filter-fix.patch" "$package/patches/030-allow-private-fix.patch" "$package/patches/040-improve-logging.patch"
before=$(snapshot)
fix_miniupnpd
[[ "$(snapshot)" == "$before" ]]
echo 'miniupnpd compatibility: PASS'
