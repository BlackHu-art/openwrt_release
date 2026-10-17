#!/usr/bin/env bash
# Integration check against the real upstream release, without a firmware toolchain.
set -euo pipefail
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
archive=${1:?Usage: verify_miniupnpd_source.sh /path/to/miniupnpd-2.3.11.tar.gz}
actual=$(sha256sum "$archive")
[[ "${actual%% *}" == 91994b127da735b2c97f19992e34420648c0e8c4ace8a4bcb0596e7685c48678 ]]
test_root=$(mktemp -d "${TMPDIR:-/tmp}/miniupnpd-source.XXXXXX")
trap 'rm -rf -- "$test_root"' EXIT
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
echo 'miniupnpd 2.3.11 full source patch stack: PASS'
