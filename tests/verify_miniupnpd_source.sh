#!/usr/bin/env bash
# Integration check against the real upstream release, without a firmware toolchain.
set -euo pipefail
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
archive=${1:?Usage: verify_miniupnpd_source.sh /path/to/miniupnpd-2.3.11.tar.gz}
actual=$(sha256sum "$archive")
[[ "${actual%% *}" == 91994b127da735b2c97f19992e34420648c0e8c4ace8a4bcb0596e7685c48678 ]]
temp_base=$(cd "${TMPDIR:-/tmp}" && pwd -P)
test_root=$(mktemp -d "$temp_base/miniupnpd-source.XXXXXX")
cleanup() {
    case "$test_root" in
        "$temp_base"/miniupnpd-source.*) rm -rf -- "$test_root" ;;
        *) echo "Refusing to remove unexpected test directory: $test_root" >&2 ;;
    esac
}
trap cleanup EXIT
BASE_PATH="$repo_root/wrt_core"
BUILD_DIR="$test_root/build"
source "$BASE_PATH/modules/target_fixes.sh"
package="$BUILD_DIR/feeds/packages/net/miniupnpd"
mkdir -p "$package/patches" "$test_root/original" "$test_root/fixed"
cp "$repo_root/tests/fixtures/miniupnpd/"*.patch "$package/patches/"
printf 'PKG_VERSION:=2.3.11\n' > "$package/Makefile"
tar -xzf "$archive" -C "$test_root/original"
tar -xzf "$archive" -C "$test_root/fixed"
original="$test_root/original/miniupnpd-2.3.11"
fixed="$test_root/fixed/miniupnpd-2.3.11"
patch -d "$original" -p1 -f -i "$package/patches/010-upnp-igdv2-compat.patch"
if patch -d "$original" -p1 -f --dry-run -i "$package/patches/020-descr-filter-fix.patch"; then
    echo 'FAIL: did not reproduce the upstream patch failure' >&2
    exit 1
fi
# 2.3.11 has further parser changes (const pointers, unsigned-char ctype,
# get_addr_or_mask), so reversing the older parser patch is no longer valid.
# Check below that we preserve the release's parser byte-for-byte instead.
patch -d "$original" -p1 -R -f --dry-run -i "$package/patches/030-allow-private-fix.patch"
fix_miniupnpd
for file in "$package/patches/"*.patch; do
    patch -d "$fixed" -p1 -f -i "$file"
done
[[ -z $(find "$fixed" -name '*.rej' -print) ]]
cmp "$original/upnppermissions.c" "$fixed/upnppermissions.c"
cmp "$original/upnppermissions.h" "$fixed/upnppermissions.h"
grep -q 'Listening for UPnP IGD (SOAP/HTTP)' "$fixed/miniupnpd.c"
grep -q 'leaseduration = 28800;' "$fixed/upnpsoap.c"
grep -q 'else if (leaseduration > 86400)' "$fixed/upnpsoap.c"
echo 'miniupnpd 2.3.11 legacy source patch stack: PASS'

# Apply the complete reviewed upstream refresh plus our lease patch to clean source.
BUILD_DIR="$test_root/upstream-build"
package="$BUILD_DIR/feeds/packages/net/miniupnpd"
fixture="$repo_root/tests/fixtures/miniupnpd/e765fb8"
mkdir -p "$package/patches" "$test_root/upstream"
cp "$fixture/"*.patch "$package/patches/"
printf 'PKG_VERSION:=2.3.11\n' > "$package/Makefile"
fix_miniupnpd
for file in "$fixture/"*.patch; do
    cmp "$file" "$package/patches/${file##*/}"
done
tar -xzf "$archive" -C "$test_root/upstream"
upstream_fixed="$test_root/upstream/miniupnpd-2.3.11"
for file in "$package/patches/"*.patch; do
    patch -d "$upstream_fixed" -p1 -f -i "$file"
done
[[ -z $(find "$upstream_fixed" -name '*.rej' -print) ]]
cmp "$original/upnppermissions.c" "$upstream_fixed/upnppermissions.c"
cmp "$original/upnppermissions.h" "$upstream_fixed/upnppermissions.h"
grep -q 'Listening for UPnP IGD (SOAP/HTTP)' "$upstream_fixed/miniupnpd.c"
grep -q 'leaseduration = 28800;' "$upstream_fixed/upnpsoap.c"
grep -q 'else if (leaseduration > 86400)' "$upstream_fixed/upnpsoap.c"
echo 'miniupnpd 2.3.11 upstream e765fb8 source patch stack: PASS'
