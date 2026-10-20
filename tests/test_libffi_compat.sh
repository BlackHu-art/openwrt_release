#!/usr/bin/env bash
set -euo pipefail
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
BASE_PATH="$repo_root/wrt_core"
source "$BASE_PATH/modules/target_fixes.sh"
temp_base=$(cd "${TMPDIR:-/tmp}" && pwd -P)
test_root=$(mktemp -d "$temp_base/libffi-compat.XXXXXX")
cleanup() {
    case "$test_root" in
        "$temp_base"/libffi-compat.*) rm -rf -- "$test_root" ;;
        *) echo "Unexpected test path: $test_root" >&2 ;;
    esac
}
trap cleanup EXIT

BUILD_DIR="$test_root/missing"
mkdir -p "$BUILD_DIR/package" "$BUILD_DIR/feeds/packages/libs"
ensure_libffi_source
cmp "$BASE_PATH/compat/libffi/Makefile" "$BUILD_DIR/package/libs/libffi/Makefile"
ensure_libffi_source

for existing in package/libs/libffi feeds/packages/libs/libffi feeds/extra/libffi; do
    BUILD_DIR="$test_root/${existing//\//-}"
    mkdir -p "$BUILD_DIR/$existing" "$BUILD_DIR/package" "$BUILD_DIR/feeds"
    printf 'existing upstream recipe\n' > "$BUILD_DIR/$existing/Makefile"
    ensure_libffi_source
    [[ $(cat "$BUILD_DIR/$existing/Makefile") == 'existing upstream recipe' ]]
    [[ $existing == package/libs/libffi || ! -e "$BUILD_DIR/package/libs/libffi" ]]
done

BUILD_DIR="$test_root/no-fallback"
BASE_PATH="$test_root/absent"
mkdir -p "$BUILD_DIR/package" "$BUILD_DIR/feeds"
if ensure_libffi_source; then
    echo "FAIL: accepted missing fallback source" >&2
    exit 1
fi
[[ ! -e "$BUILD_DIR/package/libs/libffi/Makefile" ]]
echo "libffi feed-to-core migration compatibility: PASS"
