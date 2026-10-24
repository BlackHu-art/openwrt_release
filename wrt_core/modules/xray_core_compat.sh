#!/usr/bin/env bash
# Validate the complete pinned fw876 recipe and patches before compilation.

fix_xray_core_compat() (
    local package_dir=${1:-} lowest declarations
    local go_recipe go_version go_patch patch_declarations
    local target_version=26.10.21
    if ! python3 "$BASE_PATH/managed_plugins.py" verify-staged xray-core "$package_dir"; then
        echo "错误：Xray fw876 完整配方、补丁或来源锁校验失败：$package_dir" >&2
        return 1
    fi

    go_recipe="${BUILD_DIR:?BUILD_DIR is required}/feeds/packages/lang/golang/golang/Makefile"
    if [[ ! -f "$go_recipe" ]]; then
        echo "错误：Xray $target_version 需要 Go >= 1.27.3，Go 配方不存在：$go_recipe" >&2
        return 1
    fi
    declarations=$(grep -Ec '^GO_VERSION_MAJOR_MINOR[[:space:]]*:=' "$go_recipe" || true)
    go_version=$(sed -nE 's/^GO_VERSION_MAJOR_MINOR[[:space:]]*:=[[:space:]]*([0-9]+\.[0-9]+)[[:space:]]*$/\1/p' "$go_recipe") || return 1
    if [[ "$declarations" != 1 || ! "$go_version" =~ ^[0-9]+\.[0-9]+$ ]]; then
        echo '错误：Go 配方版本字段缺失、重复或格式变化，须重新审查。' >&2
        return 1
    fi
    patch_declarations=$(grep -Ec '^GO_VERSION_PATCH[[:space:]]*:=' "$go_recipe" || true)
    go_patch=$(sed -nE 's/^GO_VERSION_PATCH[[:space:]]*:=[[:space:]]*([0-9]+)[[:space:]]*$/\1/p' "$go_recipe") || return 1
    if [[ "$patch_declarations" != 1 || ! "$go_patch" =~ ^[0-9]+$ ]]; then
        echo '错误：Go 配方 patch 版本字段缺失、重复或格式变化，须重新审查。' >&2
        return 1
    fi
    go_version="$go_version.$go_patch"
    # 1.27 是源码编译最低要求；1.27.3 同时包含官方紧急发布要求的 CA 过滤修复。
    lowest=$(printf '%s\n' 1.27.3 "$go_version" | sort -V | head -n 1) || return 1
    if [[ "$lowest" != 1.27.3 ]]; then
        echo "错误：Xray $target_version 需要 Go >= 1.27.3，当前 Go 为 $go_version。" >&2
        return 1
    fi
    echo "Xray fw876 $target_version 完整配方、补丁及 Go 版本门槛检查通过。"
)
