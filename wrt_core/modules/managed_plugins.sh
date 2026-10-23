#!/usr/bin/env bash
# Local source inputs; no network fallback for repository-owned packages.

install_managed_package() {
    local package=$1 destination=$2
    python3 "$BASE_PATH/managed_plugins.py" stage "$package" "$destination" \
        --build-root "$BUILD_DIR"
}

install_managed_custom_feed() {
    local target=$1 package
    local packages=(
        luci-app-ssr-plus xray-core chinadns-ng dns2socks dns2tcp lua-neturl
        microsocks mosdns shadowsocks-rust shadowsocksr-libev simple-obfs
        tcping v2ray-plugin ipt2socks upx
        sing-box luci-app-homeproxy oaf open-app-filter luci-app-oaf
        luci-app-istorex quickstart luci-app-quickstart luci-app-store
        taskd luci-lib-taskd luci-lib-xterm
    )
    for package in "${packages[@]}"; do
        install_managed_package "$package" "$target/$package" || return 1
    done
}

install_managed_support() {
    python3 "$BASE_PATH/managed_plugins.py" support "$1" "$2" --build-root "$BUILD_DIR"
}
