#!/usr/bin/env bash
# Prepare only the reviewed r3 UPX backport after complete source and Go checks.

fix_xray_core_compat() (
    local package_dir=${1:-} go_recipe
    go_recipe="${BUILD_DIR:?BUILD_DIR is required}/feeds/packages/lang/golang/golang/Makefile"
    if ! python3 "$BASE_PATH/xray_core_compat.py" "$package_dir" --go-recipe "$go_recipe"; then
        echo "错误：Xray fw876 完整配方、补丁、UPX 移植或 Go 版本门槛校验失败：$package_dir" >&2
        return 1
    fi
)
