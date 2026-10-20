#!/usr/bin/env bash
# 在当前稳定插件源码上回移已核实的修复；不匹配时要求重新审查。

plugin_apply_patch() {
    local package_dir=$1 git_root prefix
    shift
    # 稀疏搬运后的包没有自己的 .git。直接在父仓库子目录执行 git apply，
    # 会把补丁路径当作仓库根路径并静默跳过；显式加上真实仓库内前缀。
    if git_root=$(git -C "$package_dir" rev-parse --show-toplevel 2>/dev/null); then
        prefix=$(git -C "$package_dir" rev-parse --show-prefix) || return 1
        if [[ -n "$prefix" ]]; then
            git -C "$git_root" apply --directory="${prefix%/}" "$@"
            return $?
        fi
    fi
    git -C "$package_dir" apply "$@"
}


apply_plugin_compat_patches() {
    local package_dir=$1 label=$2 patch_file
    shift 2
    local pending=()
    if [[ ! -d "$package_dir" ]]; then
        echo "错误：$label 源码目录不存在：$package_dir" >&2
        return 1
    fi
    # 补丁互不重叠，全部预检后再写入，避免源码漂移造成部分修复。
    for patch_file in "$@"; do
        patch_file="$BASE_PATH/patches/$patch_file"
        if [[ ! -f "$patch_file" ]]; then
            echo "错误：$label 补丁不存在：$patch_file" >&2
            return 1
        elif plugin_apply_patch "$package_dir" --check "$patch_file" >/dev/null 2>&1; then
            pending+=("$patch_file")
        elif ! plugin_apply_patch "$package_dir" --reverse --check "$patch_file" >/dev/null 2>&1; then
            echo "错误：$label 源码与 ${patch_file##*/} 不匹配，停止构建以便检查上游变化。" >&2
            return 1
        fi
    done
    for patch_file in "${pending[@]}"; do
        plugin_apply_patch "$package_dir" "$patch_file" || return 1
    done
    echo "$label 兼容补丁检查完成，新增 ${#pending[@]} 项。"
}

fix_adguardhome_compat() {
    apply_plugin_compat_patches "$1" "AdGuard Home" adguardhome-update-safety.patch
}

fix_openclash_compat() {
    apply_plugin_compat_patches "$1" "OpenClash" \
        openclash-wan-subnets.patch openclash-checksum-filename.patch
}
