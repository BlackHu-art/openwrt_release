#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
BASE_PATH="$repo_root/wrt_core"
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

# Source transfer is replaced here; full local payloads and POSIX symlinks are
# checked by test_managed_build.py on Linux. Feed registration,
# missing-directory validation and install_custom_feed orchestration run as-is.
python3() { :; }
install_managed_custom_feed() {
    local package
    for package in luci-app-ssr-plus chinadns-ng dns2socks dns2tcp lua-neturl microsocks mosdns shadowsocks-rust shadowsocksr-libev simple-obfs tcping v2ray-plugin ipt2socks upx xray-core sing-box luci-app-homeproxy oaf open-app-filter luci-app-oaf \
        luci-app-istorex quickstart luci-app-quickstart luci-app-store taskd luci-lib-taskd luci-lib-xterm; do
        mkdir -p "$1/$package"
        printf 'PKG_NAME:=%s\n' "$package" > "$1/$package/Makefile"
    done
}
sync_sparse_packages_to_feed_dir() {
    local url=$1 branch=$2 target=$3 label=$4 package
    shift 4
    printf '%s|%s\n' "$url" "$branch" >> "$test_root/sources"
    for package in "$@"; do
        case "$package" in
            luci-app-ssr-plus|xray-core|chinadns-ng|dns2socks|dns2tcp|lua-neturl|microsocks|mosdns|shadowsocks-rust|shadowsocksr-libev|simple-obfs|tcping|v2ray-plugin|ipt2socks|upx)
                echo "FAIL: managed fw876 package requested remotely: $package" >&2; return 1 ;;
        esac
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
for package in luci-app-ssr-plus luci-app-partexp; do
    [[ -s "$BUILD_DIR/feeds/custom_feed/$package/Makefile" ]] || {
        echo "FAIL: requested plugin has no feed source: $package" >&2
        exit 1
    }
done
for upstream in sirpdboy/luci-app-partexp; do
    grep -Fq "https://github.com/$upstream.git|" "$test_root/sources"
done
if grep -Fq 'https://github.com/fw876/helloworld.git|' "$test_root/sources"; then
    echo 'FAIL: pinned fw876 sources were requested from rolling upstream' >&2
    exit 1
fi
for plugin in passwall passwall2; do
    [[ ! -e "$BUILD_DIR/feeds/custom_feed/luci-app-$plugin" ]]
    if grep -Fq "https://github.com/Openwrt-Passwall/openwrt-$plugin.git|" "$test_root/sources"; then
        echo "FAIL: removed $plugin repository was imported" >&2
        exit 1
    fi
done
grep -Fq "src-link custom_feed $BUILD_DIR/custom_feed" "$BUILD_DIR/$FEEDS_CONF"
echo "custom feed selected plugins: PASS"

# Exercise an unmanaged sparse import locally. Managed fw876 packages are
# covered by the production loader and the overwrite rejection Python tests.
source "$repo_root/wrt_core/modules/custom_feed.sh"
source_repo="$test_root/local-upstream"
receipt_target="$test_root/imported"
mkdir -p "$source_repo/external-example" "$receipt_target"
git -C "$source_repo" init -q
git -C "$source_repo" config user.name 'Feed regression'
git -C "$source_repo" config user.email 'feed-regression@example.invalid'
git -C "$source_repo" config core.autocrlf false
printf 'PKG_NAME:=external-example\n' > "$source_repo/external-example/Makefile"
git -C "$source_repo" add .
git -C "$source_repo" -c commit.gpgsign=false commit -qm 'Local import fixture'
git_retry() { git -c core.autocrlf=false "$@"; }
sync_sparse_packages_to_feed_dir "$source_repo" '' "$receipt_target" 'local regression' external-example
cmp "$source_repo/external-example/Makefile" "$receipt_target/external-example/Makefile"
[[ ! -e "$receipt_target/external-example/.git" ]]
echo "custom feed external package import: PASS"
