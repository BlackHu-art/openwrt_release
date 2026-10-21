#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
source "$repo_root/wrt_core/modules/custom_feed.sh"
source "$repo_root/wrt_core/modules/feeds.sh"
temp_base=$(cd "${TMPDIR:-/tmp}" && pwd -P)
test_root=$(mktemp -d "$temp_base/custom-feed-plugins.XXXXXX")
cleanup() {
    case "$test_root" in
        "$temp_base"/custom-feed-plugins.*) rm -rf -- "$test_root" ;;
        *) echo "Unexpected test path: $test_root" >&2 ;;
    esac
}
trap cleanup EXIT
BUILD_DIR="$test_root/build"
FEEDS_CONF=feeds.conf.default
mkdir -p "$BUILD_DIR"
: > "$BUILD_DIR/$FEEDS_CONF"

# Only the external repository transfer is replaced. Feed registration,
# missing-directory validation and install_custom_feed orchestration run as-is.
sync_sparse_packages_to_feed_dir() {
    local url=$1 branch=$2 target=$3 label=$4 package
    shift 4
    printf '%s|%s\n' "$url" "$branch" >> "$test_root/sources"
    for package in "$@"; do
        mkdir -p "$target/$package"
        printf 'PKG_NAME:=%s\n' "$package" > "$target/$package/Makefile"
    done
}
sync_repo_root_package_to_feed_dir() {
    mkdir -p "$3/$5"
    printf 'DEPENDS:=+luci-js-deps +luci-base\n' > "$3/$5/Makefile"
}
network_retry() {
    [[ "$*" == "./scripts/feeds update custom_feed" ]]
    mkdir -p "$BUILD_DIR/feeds"
    cp -R "$BUILD_DIR/custom_feed" "$BUILD_DIR/feeds/custom_feed"
}

install_custom_feed
for package in luci-app-passwall2 luci-app-ssr-plus luci-app-partexp; do
    [[ -s "$BUILD_DIR/feeds/custom_feed/$package/Makefile" ]] || {
        echo "FAIL: requested plugin has no feed source: $package" >&2
        exit 1
    }
done
for upstream in Openwrt-Passwall/openwrt-passwall2 fw876/helloworld sirpdboy/luci-app-partexp; do
    grep -Fq "https://github.com/$upstream.git|" "$test_root/sources"
done
grep -Fq "src-link custom_feed $BUILD_DIR/custom_feed" "$BUILD_DIR/$FEEDS_CONF"
echo "custom feed selected plugins: PASS"

# Exercise the real sparse import locally: the package loses its Git directory,
# so its exact source commit must survive in the receipt for the repair manifest.
source "$repo_root/wrt_core/modules/custom_feed.sh"
source_repo="$test_root/local-upstream"
receipt_target="$test_root/imported"
mkdir -p "$source_repo/luci-app-ssr-plus" "$receipt_target"
git -C "$source_repo" init -q
git -C "$source_repo" config user.name 'SSR regression'
git -C "$source_repo" config user.email 'ssr-regression@example.invalid'
printf 'PKG_NAME:=luci-app-ssr-plus\n' > "$source_repo/luci-app-ssr-plus/Makefile"
git -C "$source_repo" add .
git -C "$source_repo" -c commit.gpgsign=false commit -qm 'Local import fixture'
expected_revision=$(git -C "$source_repo" rev-parse HEAD)
git_retry() { git "$@"; }
sync_sparse_packages_to_feed_dir "$source_repo" '' "$receipt_target" 'local regression' luci-app-ssr-plus
[[ "$(cat "$receipt_target/luci-app-ssr-plus/.ssrplus-upstream-commit")" == "$expected_revision" ]]
[[ ! -e "$receipt_target/luci-app-ssr-plus/.git" ]]
echo "custom feed source commit receipt: PASS"
