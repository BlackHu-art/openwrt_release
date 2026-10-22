#!/usr/bin/env bash
# 保留 small-package 的 XTLS 来源，仅提升已审查配方以满足共享生成器。

fix_xray_core_compat() (
    local package_dir=${1:-} recipe patch_file blob generator minimum lowest label declarations
    local go_recipe go_version scratch='' temporary='' temp_base
    local target_version=26.7.11
    local source_blob=481e0342987bde364588e00ec716c1f23a250512
    local patched_blob=db6c4e40dfab436721c23e93f9b65d744d0636b3
    recipe="$package_dir/Makefile"
    patch_file="$BASE_PATH/patches/xray-core-26.7.11.patch"
    if [[ ! -d "$package_dir" || ! -f "$recipe" || -L "$recipe" ]]; then
        echo "错误：Xray Makefile 不存在或不是普通文件：$recipe" >&2
        return 1
    fi
    blob=$(git hash-object --no-filters "$recipe") || return 1
    if [[ "$blob" != "$source_blob" && "$blob" != "$patched_blob" ]]; then
        echo "错误：Xray Makefile 发生未审查或不完整的变化，停止构建：$recipe" >&2
        return 1
    fi

    # 每次执行都读取本轮拉取的生成器，不能让已打补丁的缓存绕过版本门槛。
    for label in Passwall Passwall2; do
        if [[ "$label" == Passwall ]]; then
            generator="$package_dir/../luci-app-passwall/luasrc/passwall/util_xray.lua"
        else
            generator="$package_dir/../luci-app-passwall2/luasrc/passwall2/util_xray.lua"
        fi
        if [[ ! -f "$generator" ]]; then
            echo "错误：$label Xray 生成器不存在：$generator" >&2
            return 1
        fi
        declarations=$(grep -Ec '^[[:space:]]*local[[:space:]]+xray_min_version[[:space:]]*=' "$generator" || true)
        minimum=$(sed -nE 's/^[[:space:]]*local[[:space:]]+xray_min_version[[:space:]]*=[[:space:]]*"([0-9]+\.[0-9]+\.[0-9]+)"[[:space:]]*$/\1/p' "$generator") || return 1
        if [[ "$declarations" != 1 || ! "$minimum" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
            echo "错误：$label Xray 最低版本声明缺失、重复或格式变化，须重新审查。" >&2
            return 1
        fi
        lowest=$(printf '%s\n' "$target_version" "$minimum" | sort -V | head -n 1) || return 1
        if [[ "$lowest" != "$minimum" ]]; then
            echo "错误：$label 要求 Xray >= $minimum，已审查配方只有 $target_version，停止构建。" >&2
            return 1
        fi
    done

    go_recipe="${BUILD_DIR:?BUILD_DIR is required}/feeds/packages/lang/golang/golang/Makefile"
    if [[ ! -f "$go_recipe" ]]; then
        echo "错误：Xray $target_version 需要 Go >= 1.26，Go 配方不存在：$go_recipe" >&2
        return 1
    fi
    declarations=$(grep -Ec '^GO_VERSION_MAJOR_MINOR[[:space:]]*:=' "$go_recipe" || true)
    go_version=$(sed -nE 's/^GO_VERSION_MAJOR_MINOR[[:space:]]*:=[[:space:]]*([0-9]+\.[0-9]+)[[:space:]]*$/\1/p' "$go_recipe") || return 1
    if [[ "$declarations" != 1 || ! "$go_version" =~ ^[0-9]+\.[0-9]+$ ]]; then
        echo '错误：Go 配方版本字段缺失、重复或格式变化，须重新审查。' >&2
        return 1
    fi
    lowest=$(printf '%s\n' 1.26 "$go_version" | sort -V | head -n 1) || return 1
    if [[ "$lowest" != 1.26 ]]; then
        echo "错误：Xray $target_version 需要 Go >= 1.26，当前 Go 为 $go_version。" >&2
        return 1
    fi
    if [[ "$blob" == "$patched_blob" ]]; then
        echo "Xray $target_version 配方及共享生成器版本门槛检查通过。"
        return 0
    fi
    if [[ ! -f "$patch_file" ]]; then
        echo "错误：Xray 兼容补丁不存在：$patch_file" >&2
        return 1
    fi

    # 独立 Git 根避免被上级仓库的路径前缀影响；全程验证后只原子发布一个文件。
    temp_base=$(cd "${TMPDIR:-/tmp}" && pwd -P) || return 1
    scratch=$(mktemp -d "$temp_base/xray-core-compat.XXXXXX") || return 1
    trap 'case "$scratch" in "$temp_base"/xray-core-compat.*) rm -rf -- "$scratch" ;; esac; [[ -z "$temporary" ]] || rm -f -- "$temporary"' EXIT
    git init -q "$scratch" || return 1
    git -C "$scratch" config core.autocrlf false || return 1
    cp -p "$recipe" "$scratch/Makefile" || return 1
    if ! git -C "$scratch" apply --check "$patch_file" || ! git -C "$scratch" apply "$patch_file"; then
        echo '错误：Xray 兼容补丁无法应用，原配方未改动。' >&2
        return 1
    fi
    if [[ $(git hash-object --no-filters "$scratch/Makefile") != "$patched_blob" ]]; then
        echo '错误：Xray 补丁结果与已审查的版本、下载来源和源码哈希不一致，原配方未改动。' >&2
        return 1
    fi
    temporary=$(mktemp "$package_dir/.xray-core-compat.XXXXXX") || return 1
    cp -p "$scratch/Makefile" "$temporary" || return 1
    mv -f -- "$temporary" "$recipe" || return 1
    temporary=''
    echo "Xray 配方已更新到 $target_version，共享生成器和 Go 版本检查通过。"
)
