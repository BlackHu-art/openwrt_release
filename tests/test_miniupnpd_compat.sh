#!/usr/bin/env bash
set -euo pipefail
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
BASE_PATH="$repo_root/wrt_core"
source "$BASE_PATH/modules/target_fixes.sh"
temp_base=$(cd "${TMPDIR:-/tmp}" && pwd -P)
test_root=$(mktemp -d "$temp_base/miniupnpd-compat.XXXXXX")
cleanup() {
    case "$test_root" in
        "$temp_base"/miniupnpd-compat.*) rm -rf -- "$test_root" ;;
        *) echo "Refusing to remove unexpected test directory: $test_root" >&2 ;;
    esac
}
trap cleanup EXIT
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

# ImmortalWrt e765fb8 already refreshed the complete stack. Keep it byte-for-byte.
cp "$fixture/e765fb8/"*.patch "$package/patches/"
before=$(snapshot)
if ! fix_miniupnpd; then
    echo 'FAIL: the reviewed upstream patch refresh was rejected' >&2
    exit 1
fi
[[ "$(snapshot)" == "$before" ]]
for file in "$fixture/e765fb8/"*.patch; do
    cmp "$file" "$package/patches/${file##*/}"
done
fix_miniupnpd
[[ "$(snapshot)" == "$before" ]]

# A mixed cache may retain known obsolete patches beside the refreshed logging patch.
cp "$fixture/020-descr-filter-fix.patch" "$fixture/030-allow-private-fix.patch" "$package/patches/"
fix_miniupnpd
[[ "$(snapshot)" == "$before" ]]

# Recognizing the logging patch must not bypass validation of the remaining stack.
cp "$fixture/020-descr-filter-fix.patch" "$package/patches/"
printf '\nupstream drift\n' >> "$package/patches/020-descr-filter-fix.patch"
before=$(snapshot)
if fix_miniupnpd; then
    echo 'FAIL: upstream logging bypassed validation of an unknown parser patch' >&2
    exit 1
fi
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
