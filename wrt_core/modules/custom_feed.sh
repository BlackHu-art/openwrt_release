#!/usr/bin/env bash
# custom_feed 同步、注册和路径辅助。

get_custom_feed_name() {
    printf '%s\n' "custom_feed"
}


get_custom_feed_source_dir() {
    # install 前本地 src-link 的源目录。
    printf '%s\n' "$BUILD_DIR/$(get_custom_feed_name)"
}


get_custom_feed_worktree_dir() {
    # feeds update 后生成的 feeds/custom_feed 工作树。
    printf '%s\n' "$BUILD_DIR/feeds/$(get_custom_feed_name)"
}


get_custom_feed_package_dir() {
    # feeds install 后生成的 package/feeds/custom_feed 目录。
    printf '%s\n' "$BUILD_DIR/package/feeds/$(get_custom_feed_name)"
}


sync_sparse_packages_to_feed_dir() (
    local repo_url="$1"
    local repo_branch="$2"
    local target_dir="$3"
    local repo_label="$4"
    shift 4

    local packages=("$@")
    local tmp_dir="" source_dir pkg target
    local attempted=()
    local missing_packages=()
    local clone_args=(clone --depth 1 --filter=blob:none --sparse)
    local commit_sha=""

    python3 "$BASE_PATH/managed_plugins.py" assert-external "${packages[@]}" || return 1
    mkdir -p "$target_dir" || return 1
    # Rename publication must stay on the target filesystem, even when TMPDIR
    # is a different mount. Backups also stay here for ordinary I/O rollback.
    tmp_dir=$(mktemp -d "$target_dir/.feed-sync.XXXXXX") || return 1
    source_dir="$tmp_dir/source"
    cleanup_sparse_import() {
        local status=$? rollback_failed=0 index pkg target
        trap - EXIT
        if [[ $status != 0 ]]; then
            for ((index=${#attempted[@]}-1; index>=0; index--)); do
                pkg=${attempted[index]}
                target="$target_dir/$pkg"
                if ! rm -rf -- "$target"; then
                    rollback_failed=1
                    continue
                fi
                if [[ -e "$tmp_dir/previous/$pkg" || -L "$tmp_dir/previous/$pkg" ]]; then
                    if ! mv -- "$tmp_dir/previous/$pkg" "$target"; then
                        rollback_failed=1
                    fi
                fi
            done
        fi
        if [[ $rollback_failed == 1 ]]; then
            echo "错误：$repo_label 回滚失败，原有包备份保留在 $tmp_dir/previous。" >&2
            exit 1
        fi
        if ! rm -rf -- "$tmp_dir"; then
            echo "错误：无法清理 $repo_label 的暂存目录 $tmp_dir。" >&2
            exit 1
        fi
        exit "$status"
    }
    trap cleanup_sparse_import EXIT

    # A full commit in the ref position is immutable. Branch/empty callers
    # keep their existing rolling behavior.
    if [[ "$repo_branch" =~ ^[0-9a-f]{40}$ ]]; then
        commit_sha="$repo_branch"
    elif [ -n "$repo_branch" ]; then
        clone_args+=(-b "$repo_branch")
    fi

    clone_args+=("$repo_url" "$source_dir")

    echo "正在从 $repo_label 稀疏同步指定目录..."
    if ! git_retry "${clone_args[@]}"; then
        echo "错误：从 $repo_url 拉取仓库骨架失败" >&2
        return 1
    fi

    # Never publish the cloned default HEAD if a reviewed pin is unavailable.
    if [[ -n "$commit_sha" ]]; then
        if ! git_retry -C "$source_dir" fetch --depth 1 origin "$commit_sha" ||
           ! git_retry -C "$source_dir" checkout --detach "$commit_sha" ||
           [[ $(git -C "$source_dir" rev-parse HEAD) != "$commit_sha" ]]; then
            echo "错误：无法固定 $repo_label 到已审查提交 $commit_sha。" >&2
            return 1
        fi
    fi

    if ! git_retry -C "$source_dir" sparse-checkout set "${packages[@]}"; then
        echo "错误：配置 $repo_label 稀疏检出目录失败" >&2
        return 1
    fi

    # Validate every requested input before replacing any existing package.
    for pkg in "${packages[@]}"; do
        if [[ ! "$pkg" =~ ^[a-zA-Z0-9][a-zA-Z0-9._+-]*$ ||
              ! -d "$source_dir/$pkg" || -L "$source_dir/$pkg" ]]; then
            missing_packages+=("$pkg")
        fi
    done
    if [[ ${#missing_packages[@]} != 0 ]]; then
        printf '错误：%s 仓库缺少以下必要目录：\n' "$repo_label" >&2
        printf '  - %s\n' "${missing_packages[@]}" >&2
        return 1
    fi

    mkdir -p "$tmp_dir/previous" || return 1
    for pkg in "${packages[@]}"; do
        target="$target_dir/$pkg"
        if [[ -e "$target" || -L "$target" ]]; then
            # Leave the old tree untouched until every backup is complete.
            cp -a -- "$target" "$tmp_dir/previous/$pkg" || return 1
        fi
    done
    for pkg in "${packages[@]}"; do
        target="$target_dir/$pkg"
        attempted+=("$pkg")
        if ! rm -rf -- "$target" || ! mv -- "$source_dir/$pkg" "$target"; then
            echo "错误：无法发布 $repo_label 的 $pkg；恢复已有包。" >&2
            return 1
        fi
    done
    return 0
)


sync_repo_root_package_to_feed_dir() {
    local repo_url="$1"
    local repo_branch="$2"
    local target_dir="$3"
    local repo_label="$4"
    local package_name="$5"
    local commit_sha="${6:-}"
    local tmp_dir
    local clone_args=(clone --depth 1 --filter=blob:none)

    python3 "$BASE_PATH/managed_plugins.py" assert-external "$package_name" || return 1
    if [[ -n "$commit_sha" && ! "$commit_sha" =~ ^[0-9a-f]{40}$ ]]; then
        echo "错误：$repo_label 必须使用完整提交 SHA。" >&2
        return 1
    fi
    tmp_dir=$(mktemp -d)

    if [ -n "$repo_branch" ]; then
        clone_args+=(-b "$repo_branch")
    fi

    clone_args+=("$repo_url" "$tmp_dir")

    echo "正在从 $repo_label 同步单包仓库..."
    if ! git_retry "${clone_args[@]}"; then
        echo "错误：从 $repo_url 克隆 $repo_label 失败" >&2
        rm -rf "$tmp_dir"
        return 1
    fi

    if [[ -n "$commit_sha" ]]; then
        if ! git_retry -C "$tmp_dir" fetch --depth 1 origin "$commit_sha" ||
           ! git_retry -C "$tmp_dir" checkout --detach "$commit_sha" ||
           [[ $(git -C "$tmp_dir" rev-parse HEAD) != "$commit_sha" ]]; then
            echo "错误：无法固定 $repo_label 到已审查提交 $commit_sha。" >&2
            rm -rf "$tmp_dir"
            return 1
        fi
    fi

    if [ ! -f "$tmp_dir/Makefile" ]; then
        echo "错误：$repo_label 仓库根目录缺少 OpenWrt 软件包 Makefile" >&2
        rm -rf "$tmp_dir"
        return 1
    fi

    rm -rf "$tmp_dir/.git"
    rm -rf "$target_dir/$package_name"

    if ! mv "$tmp_dir" "$target_dir/$package_name"; then
        echo "错误：无法将 $repo_label 移动到 $target_dir/$package_name" >&2
        rm -rf "$tmp_dir"
        return 1
    fi
}


remove_nested_airoha_npu_package() {
    local package_dir="$1"
    [[ -f "$package_dir/Makefile" ]] || return 1
    if [[ -f "$package_dir/luci-app-airoha-npu/Makefile" ]]; then
        rm -rf "$package_dir/luci-app-airoha-npu" || return 1
    fi
}


fix_airoha_npu_luci_mk() {
    local package_dir="$1" makefile_path
    [[ -f "$package_dir/Makefile" ]] || return 1
    while IFS= read -r -d '' makefile_path; do
        if grep -qE '^[[:space:]]*include[[:space:]]+\.\./\.\./luci\.mk[[:space:]]*$' "$makefile_path"; then
            sed -i -E 's|^[[:space:]]*include[[:space:]]+\.\./\.\./luci\.mk[[:space:]]*$|include $(TOPDIR)/feeds/luci/luci.mk|' "$makefile_path" || return 1
        fi
    done < <(find "$package_dir" -type f -name Makefile -print0)
}


fix_emmc_health_luci_js_deps() {
    local package_dir="$1"
    local makefile_path="$package_dir/Makefile"

    if [ ! -f "$makefile_path" ]; then
        echo "错误：luci-app-emmc-health Makefile 不存在：$makefile_path" >&2
        return 1
    fi

    if grep -q "luci-js-deps" "$makefile_path"; then
        sed -i '/^[[:space:]]*DEPENDS:=/ s/[[:space:]]*+luci-js-deps//g' "$makefile_path"
        echo "已移除 luci-app-emmc-health 的 luci-js-deps 兼容性依赖。"
    fi
}


register_local_feed_source() {
    local custom_feed_dir="$1"
    local feeds_path="$2"
    local feed_name
    feed_name=$(get_custom_feed_name)
    local worktree="$BUILD_DIR/feeds/$feed_name"
    if [[ -e "$worktree" || -L "$worktree" ]]; then
        if [[ ! -L "$worktree" || $(readlink "$worktree") != "$custom_feed_dir" ]]; then
            echo "错误：$feed_name 工作目录没有指向本次构建来源：$worktree" >&2
            return 1
        fi
    else
        mkdir -p "$BUILD_DIR/feeds" || return 1
        ln -s "$custom_feed_dir" "$worktree" || return 1
    fi

    sed -i "/[[:space:]]$feed_name[[:space:]]/d" "$feeds_path"
    [ -z "$(tail -c 1 "$feeds_path")" ] || echo "" >>"$feeds_path"
    echo "src-link $feed_name $custom_feed_dir" >>"$feeds_path"
    echo "已将 $feed_name 作为本地源 (src-link) 添加到 $feeds_path"
}


install_custom_feed() {
    local feeds_path
    local fullconenat_nft_dir="$BUILD_DIR/package/network/utils/fullconenat-nft"
    local fullconenat_dir="$BUILD_DIR/package/network/utils/fullconenat"
    local custom_feed_dir
    local custom_feed_worktree_dir
    local custom_feed_name
    local core_url="${REPO_URL:-}" airoha_npu_required=0 netcontrol_required=0

    local base_custom_feed_packages=(
        xray-plugin haproxy hysteria \
        naiveproxy v2ray-core v2ray-geodata geoview \
        tuic-client trojan-plus \
        v2dat adguardhome luci-app-adguardhome ddns-go \
        luci-app-ddns-go luci-app-cloudflarespeedtest netdata luci-app-netdata \
        lucky luci-app-lucky luci-app-openclash luci-app-amlogic \
        easytier luci-app-easytier \
        msd_lite luci-app-msd_lite
    )
    local required_feed_dirs=(
        tcping v2ray-geodata luci-lib-taskd luci-app-openclash
        luci-app-quickstart luci-app-store luci-app-homeproxy luci-app-mosdns
        luci-app-ssr-plus luci-app-partexp
        nikki luci-app-nikki mihomo-meta
        open-app-filter luci-app-oaf lucky luci-app-lucky luci-app-easytier
        luci-app-emmc-health
    )
    local custom_feed_sources=()
    local missing_feed_dirs=()
    local source_entry
    local repo_label
    local repo_url
    local repo_branch
    local repo_packages
    local repo_package_array=()

    while [[ "$core_url" == */ ]]; do core_url=${core_url%/}; done
    if [[ ${core_url%.git} == https://github.com/ZqinKing/immortalwrt &&
          ${COMMIT_HASH:-} == 796897b5417537c0b10ee9ec31166ac5901bc33b ]]; then
        airoha_npu_required=1
        required_feed_dirs+=(luci-app-airoha-npu)
    fi
    if [[ ${core_url%.git} == https://github.com/padavanonly/immortalwrt-mt798x-6.6 &&
          ${COMMIT_HASH:-} == ec9ef10efc65da1e6d1de4e2c043c0e13d08eed8 ]]; then
        netcontrol_required=1
        required_feed_dirs+=(luci-app-netcontrol)
    fi

    if [ ! -d "$fullconenat_nft_dir" ]; then
        base_custom_feed_packages+=(fullconenat-nft)
    fi
    if [ ! -d "$fullconenat_dir" ]; then
        base_custom_feed_packages+=(fullconenat)
    fi

    # 统一从外部仓库同步指定包，避免分散维护 feeds.conf。
    custom_feed_sources=(
        "kenzok8/small-package|https://github.com/kenzok8/small-package.git||${base_custom_feed_packages[*]}"
        "sbwml/luci-app-mosdns|https://github.com/sbwml/luci-app-mosdns.git|v5|luci-app-mosdns"
        "sirpdboy/luci-app-partexp|https://github.com/sirpdboy/luci-app-partexp.git|main|luci-app-partexp"
        "nikkinikki-org/OpenWrt-nikki|https://github.com/nikkinikki-org/OpenWrt-nikki.git|main|nikki luci-app-nikki mihomo-meta"
    )
    # S20M already selects Netcontrol, but its pinned core and 24.10 LuCI feed
    # do not contain that recipe. Keep the canonical source pinned and scoped
    # to this core instead of silently losing the requested plugin at defconfig.
    if [[ $netcontrol_required == 1 ]]; then
        custom_feed_sources+=(
            "rule2c/luci-app-netcontrol|https://github.com/rule2c/luci-app-netcontrol.git|61364846e1188d87801f778749efc4f2a4deac43|luci-app-netcontrol"
        )
    fi

    feeds_path=$(get_feeds_path)
    custom_feed_name=$(get_custom_feed_name)
    custom_feed_dir=$(get_custom_feed_source_dir)
    custom_feed_worktree_dir=$(get_custom_feed_worktree_dir)

    # Verify all repository-owned inputs before discarding any old feed tree.
    python3 "$BASE_PATH/managed_plugins.py" check || return 1
    if [ -d "$custom_feed_dir" ]; then
        echo "清理旧的自定义 feed 目录..."
        rm -rf "$custom_feed_dir"
    fi
    mkdir -p "$custom_feed_dir"

    install_managed_custom_feed "$custom_feed_dir" || return 1

    for source_entry in "${custom_feed_sources[@]}"; do
        IFS='|' read -r repo_label repo_url repo_branch repo_packages <<< "$source_entry"
        read -r -a repo_package_array <<< "$repo_packages"

        if ! sync_sparse_packages_to_feed_dir "$repo_url" "$repo_branch" "$custom_feed_dir" "$repo_label" "${repo_package_array[@]}"; then
            rm -rf "$custom_feed_dir"
            return 1
        fi
    done

    if [[ $netcontrol_required == 1 ]]; then
        # Adding this missing plugin must not migrate, stop or disable a
        # separately installed Timecontrol service on the user's router.
        if ! python3 "$BASE_PATH/netcontrol_compat.py" "$custom_feed_dir/luci-app-netcontrol"; then
            rm -rf "$custom_feed_dir"
            return 1
        fi
    fi

    if ! sync_repo_root_package_to_feed_dir "https://github.com/adminchenyu/eMMC-Health.git" "main" "$custom_feed_dir" "adminchenyu/eMMC-Health" "luci-app-emmc-health"; then
        rm -rf "$custom_feed_dir"
        return 1
    fi

    # Existing W1701K configuration selects this package, which neither its
    # pinned core nor the LuCI feed supplies. Backport upstream e16d7ace source
    # wiring while fixing the input to the reviewed package commit.
    if [[ $airoha_npu_required == 1 ]]; then
        if ! sync_repo_root_package_to_feed_dir "https://github.com/rchen14b/luci-app-airoha-npu.git" "main" "$custom_feed_dir" "rchen14b/luci-app-airoha-npu" "luci-app-airoha-npu" "14521b8414da1e98517a295d8ec267087c7dde8e" ||
           ! remove_nested_airoha_npu_package "$custom_feed_dir/luci-app-airoha-npu" ||
           ! fix_airoha_npu_luci_mk "$custom_feed_dir/luci-app-airoha-npu"; then
            rm -rf "$custom_feed_dir"
            return 1
        fi
    fi

    if ! fix_emmc_health_luci_js_deps "$custom_feed_dir/luci-app-emmc-health"; then
        rm -rf "$custom_feed_dir"
        return 1
    fi

    register_local_feed_source "$custom_feed_dir" "$feeds_path" || return 1

    echo "正在更新 $custom_feed_name 本地 feed 索引..."
    run_feed_index custom "$custom_feed_name" || return 1

    collect_missing_directories "$custom_feed_worktree_dir" required_feed_dirs missing_feed_dirs

    if [ ${#missing_feed_dirs[@]} -ne 0 ]; then
        printf '错误：%s 本地 feed 未生成以下仓库依赖路径：\n' "$custom_feed_name" >&2
        printf '  - %s\n' "${missing_feed_dirs[@]}" >&2
        return 1
    fi

    echo "$custom_feed_name 指定包处理完成并已成功加载到 feeds 体系中！"
}


collect_missing_directories() {
    local base_dir="$1"
    local -n required_dirs_ref="$2"
    local -n missing_dirs_ref="$3"
    local dir_name

    for dir_name in "${required_dirs_ref[@]}"; do
        if [ ! -d "$base_dir/$dir_name" ]; then
            missing_dirs_ref+=("${base_dir#$BUILD_DIR/}/$dir_name")
        fi
    done
}
