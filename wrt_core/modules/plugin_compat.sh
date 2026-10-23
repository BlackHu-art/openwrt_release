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

fix_adguardhome_compat() (
    local package_dir=$1 table="$BASE_PATH/compat/adguardhome/source-files.tsv"
    local temp_base scratch patch_file path blob temporary i
    local patches=(adguardhome-update-safety.patch adguardhome-noop-update.patch) files=()
    [[ -d "$package_dir" && -s "$table" ]] || {
        echo '错误：AdGuard Home 源码或基线清单不存在。' >&2; return 1;
    }
    for patch_file in "${patches[@]}"; do
        [[ -s "$BASE_PATH/patches/$patch_file" ]] || {
            echo "错误：AdGuard Home 补丁不存在：$patch_file" >&2; return 1;
        }
    done
    temp_base=$(cd "${TMPDIR:-/tmp}" && pwd -P) || return 1
    scratch=$(mktemp -d "$temp_base/adguard-compat.XXXXXX") || return 1
    case "$scratch" in
        "$temp_base"/adguard-compat.*) trap 'rm -rf -- "$scratch"' EXIT ;;
        *) echo '错误：AdGuard Home 临时目录不在指定范围内。' >&2; return 1 ;;
    esac
    git init -q "$scratch" || return 1
    git -C "$scratch" config core.autocrlf false || return 1
    while read -r blob path; do
        [[ -n "$blob" && -n "$path" && -f "$package_dir/$path" ]] || return 1
        files+=("$path")
        mkdir -p "$scratch/$(dirname "$path")" || return 1
        cp -p "$package_dir/$path" "$scratch/$path" || return 1
    done < "$table"
    [[ ${#files[@]} -eq 3 ]] || return 1
    # The UPX removal overlaps the older patch's context. Normalize complete
    # patches in reverse order in scratch, never in the real source package.
    for ((i=${#patches[@]}-1; i>=0; i--)); do
        patch_file="$BASE_PATH/patches/${patches[$i]}"
        if git -C "$scratch" apply --reverse --check "$patch_file" >/dev/null 2>&1; then
            git -C "$scratch" apply --reverse "$patch_file" || return 1
        fi
    done
    while read -r blob path; do
        if [[ $(git hash-object --no-filters "$scratch/$path") != "$blob" ]]; then
            echo "错误：AdGuard Home 上游文件发生未审查或不完整的变化：$path" >&2
            return 1
        fi
    done < "$table"
    for patch_file in "${patches[@]}"; do
        git -C "$scratch" apply "$BASE_PATH/patches/$patch_file" || return 1
    done
    for path in "${files[@]}"; do
        cmp -s "$scratch/$path" "$package_dir/$path" && continue
        temporary=$(mktemp "$package_dir/$path.adgfix.XXXXXX") || return 1
        if ! cp -p "$scratch/$path" "$temporary" || ! mv -f "$temporary" "$package_dir/$path"; then
            rm -f -- "$temporary"
            return 1
        fi
    done
    echo 'AdGuard Home 兼容补丁与受保护源码检查完成。'
)

fix_openclash_compat() {
    apply_plugin_compat_patches "$1" "OpenClash" \
        openclash-wan-subnets.patch openclash-checksum-filename.patch \
        openclash-ruby-ast.patch openclash-dashboard-switch.patch openclash-filename-safety.patch \
        openclash-tun-stack.patch
}

fix_passwall2_compat() {
    apply_plugin_compat_patches "$1" "Passwall2" \
        passwall2-singbox-tls-pin.patch passwall2-singbox-launch.patch \
        passwall2-fw876-core-update.patch
}

fix_ssrplus_compat() (
    # v198.2 startup and DNS remain byte-identical to fw876; the generator
    # receives only the separately reviewed Xray transport API adaptation.
    # The preparer checks every upstream file before publishing integration.
    python "$BASE_PATH/ssrplus_verify.py" prepare --core "$BASE_PATH" --package "$1"
)
