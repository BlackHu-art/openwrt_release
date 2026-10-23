#!/usr/bin/env bash
# Fail before compilation/firmware collection when the selected fw876 integration is incomplete.
SSRP_BUILD_CORE_PATH=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

verify_ssrplus_final_config() {
    local config=${1:-.config} key
    grep -qE '^CONFIG_PACKAGE_luci-app-ssr-plus=[ym]$' "$config" || return 0
    for key in CONFIG_PACKAGE_firewall4 CONFIG_PACKAGE_dnsmasq-full \
        CONFIG_PACKAGE_dnsmasq_full_nftset CONFIG_PACKAGE_flock \
        CONFIG_PACKAGE_ipt2socks CONFIG_PACKAGE_dns2socks \
        CONFIG_PACKAGE_luci-app-ssr-plus_Nftables_Transparent_Proxy; do
        if ! grep -qxF "$key=y" "$config"; then
            echo "SSR build rejected: final configuration requires $key=y" >&2
            return 1
        fi
    done
    if grep -qxF 'CONFIG_PACKAGE_luci-app-ssr-plus_Iptables_Transparent_Proxy=y' "$config"; then
        echo 'SSR build rejected: nft integration selected with the iptables backend' >&2
        return 1
    fi
}

verify_ssrplus_built_artifacts() {
    local manifest package root found=0 root_found=0 apk_tool key value
    local global_selected=0 device_selected=0 device_root_found=0
    local apk_args=()
    grep -qE '^CONFIG_PACKAGE_luci-app-ssr-plus=[ym]$' .config || return 0
    verify_ssrplus_final_config .config || return 1
    manifest=feeds/custom_feed/luci-app-ssr-plus/root/usr/share/shadowsocksr/ssrplus-build.json
    [[ -s "$manifest" ]] || { echo 'SSR build rejected: trusted source manifest missing' >&2; return 1; }
    [[ -d bin ]] || { echo 'SSR build rejected: compiled output directory missing' >&2; return 1; }
    for apk_tool in staging_dir/host/bin/apk staging_dir/hostpkg/bin/apk; do
        if [[ -x "$apk_tool" ]]; then apk_args=(--apk-tool "$(pwd)/$apk_tool"); break; fi
    done
    while IFS= read -r -d '' package; do
        found=1
        python "$SSRP_BUILD_CORE_PATH/ssrplus_verify.py" package \
            --manifest "$manifest" --package "$package" "${apk_args[@]}" || return 1
    done < <(find bin -type f \( -name 'luci-app-ssr-plus_*.ipk' -o -name 'luci-app-ssr-plus-*.apk' \) -print0)
    [[ "$found" = 1 ]] || { echo 'SSR build rejected: compiled IPK/APK missing' >&2; return 1; }
    if grep -qxF 'CONFIG_PACKAGE_luci-app-ssr-plus=y' .config; then
        global_selected=1
        [[ -d build_dir ]] || { echo 'SSR build rejected: final rootfs directory missing' >&2; return 1; }
        while IFS= read -r -d '' root; do
            root_found=1
            python "$SSRP_BUILD_CORE_PATH/ssrplus_verify.py" rootfs \
                --manifest "$manifest" --root "$root" || return 1
        done < <(find build_dir -mindepth 2 -maxdepth 2 -type d -name 'root-*' -print0)
        [[ "$root_found" = 1 ]] || { echo 'SSR build rejected: final rootfs missing' >&2; return 1; }
    fi
    grep -qxF 'CONFIG_TARGET_PER_DEVICE_ROOTFS=y' .config || return 0
    # Only positive package entries on an enabled device request installation.
    while IFS='=' read -r key value; do
        [[ "$key" == CONFIG_TARGET_DEVICE_PACKAGES_* ]] || continue
        grep -qxF "${key/CONFIG_TARGET_DEVICE_PACKAGES_/CONFIG_TARGET_DEVICE_}=y" .config || continue
        value=${value%$'\r'}
        value=${value#\"}
        value=${value%\"}
        for package in $value; do
            [[ "$package" != luci-app-ssr-plus ]] || device_selected=1
        done
    done < .config
    [[ "$global_selected" = 1 || "$device_selected" = 1 ]] || return 0
    [[ -d build_dir ]] || { echo 'SSR build rejected: per-device rootfs directory missing' >&2; return 1; }
    # include/image.mk feeds mkfs from KDIR/target-dir-<8-digit package MD5>,
    # where KDIR is build_dir/target-*/linux-*. Exclude nested work/temp roots.
    while IFS= read -r -d '' root; do
        if [[ "$global_selected" != 1 &&
              ! -e "$root/usr/share/shadowsocksr/ssrplus-build.json" &&
              ! -e "$root/etc/init.d/shadowsocksr" ]] &&
            ! grep -qxF 'Package: luci-app-ssr-plus' "$root/usr/lib/opkg/status" 2>/dev/null &&
            ! grep -qxF 'P:luci-app-ssr-plus' "$root/lib/apk/db/installed" 2>/dev/null; then
            continue
        fi
        device_root_found=1
        python "$SSRP_BUILD_CORE_PATH/ssrplus_verify.py" rootfs \
            --manifest "$manifest" --root "$root" || return 1
    done < <(find build_dir -regextype posix-extended -mindepth 3 -maxdepth 3 -type d \
        -regex 'build_dir/target-[^/]+/linux-[^/]+/target-dir-[0-9a-f]{8}' -print0)
    [[ "$device_root_found" = 1 ]] || { echo 'SSR build rejected: installed per-device SSR rootfs missing' >&2; return 1; }
}
