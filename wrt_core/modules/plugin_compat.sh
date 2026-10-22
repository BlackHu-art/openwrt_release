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

fix_ssrplus_compat() (
    local package_dir=$1 runtime_source="$BASE_PATH/compat/ssrplus/runtime.sh"
    local runtime_path=root/usr/share/shadowsocksr/ssrp-runtime.sh
    local scratch patch_file path blob fixture i source_commit temporary
    local patches=() files=() manifest_args=()
    [[ -d "$package_dir" && -f "$runtime_source" && -f "$BASE_PATH/ssrplus_verify.py" ]] || {
        echo '错误：SSR Plus 源码、辅助脚本或成品校验工具不存在。' >&2; return 1;
    }
    while IFS= read -r patch_file; do
        [[ -n "$patch_file" && -s "$BASE_PATH/patches/$patch_file" ]] || {
            echo "错误：SSR Plus 补丁不存在：$patch_file" >&2; return 1;
        }
        patches+=("$BASE_PATH/patches/$patch_file")
        manifest_args+=(--patch "$BASE_PATH/patches/$patch_file")
    done < "$BASE_PATH/compat/ssrplus/patches.list"
    if [[ -e "$package_dir/$runtime_path" ]] && ! cmp -s "$runtime_source" "$package_dir/$runtime_path"; then
        echo '错误：SSR Plus 已有未知版本的兼容运行脚本，停止构建。' >&2
        return 1
    fi
    scratch=$(mktemp -d) || return 1
    trap 'rm -rf -- "$scratch"' EXIT
    # A separate Git root also prevents apply from silently skipping paths when
    # TMPDIR happens to live inside another repository.
    git init -q "$scratch" || return 1
    git -C "$scratch" config core.autocrlf false || return 1
    while read -r blob path fixture; do
        files+=("$path")
        mkdir -p "$scratch/$(dirname "$path")" || return 1
        cp "$package_dir/$path" "$scratch/$path" || return 1
        [[ "$path" != root/* ]] || manifest_args+=(--file "/${path#root/}")
    done < "$BASE_PATH/compat/ssrplus/source-files.tsv"
    # Dependent extensions are undone in reverse order. Unknown/incomplete
    # states fail closed before any real package file is touched.
    for ((i=${#patches[@]}-1; i>=0; i--)); do
        patch_file=${patches[$i]}
        if git -C "$scratch" apply --reverse --check "$patch_file" >/dev/null 2>&1; then
            git -C "$scratch" apply --reverse "$patch_file" || return 1
        fi
    done
    while read -r blob path fixture; do
        if [[ $(git hash-object --no-filters "$scratch/$path") != "$blob" ]]; then
            echo "错误：SSR Plus 上游文件发生未审查或不完整的变化：$path" >&2
            return 1
        fi
    done < "$BASE_PATH/compat/ssrplus/source-files.tsv"
    for patch_file in "${patches[@]}"; do
        git -C "$scratch" apply "$patch_file" || return 1
    done
    install -m 755 "$runtime_source" "$scratch/$runtime_path" || return 1
    for path in "${files[@]}"; do
        case "$path" in
            root/usr/share/shadowsocksr/shadowsocksr.config) chmod 644 "$scratch/$path" || return 1 ;;
            root/*) chmod 755 "$scratch/$path" || return 1 ;;
        esac
    done
    source_commit=2abdc9aa9e19607774dc9789709212b70b8607c6
    if [[ -f "$package_dir/.ssrplus-upstream-commit" ]]; then
        source_commit=$(cat "$package_dir/.ssrplus-upstream-commit") || return 1
        [[ "$source_commit" =~ ^[0-9a-f]{40}$ ]] || { echo "错误：SSR Plus 来源提交记录无效。" >&2; return 1; }
    fi
    MSYS2_ARG_CONV_EXCL="${MSYS2_ARG_CONV_EXCL:+$MSYS2_ARG_CONV_EXCL;}/etc/;/usr/" \
    python "$BASE_PATH/ssrplus_verify.py" manifest --root "$scratch/root" \
        --output "$scratch/root/usr/share/shadowsocksr/ssrplus-build.json" \
        --source-commit "$source_commit" --repair-version 190-r10 --file-mode 0755 \
        --file-mode-override /usr/share/shadowsocksr/shadowsocksr.config=0644 \
        "${manifest_args[@]}" --file /usr/share/shadowsocksr/ssrp-runtime.sh || return 1
    # Validation and artifact construction succeeded; publish the reviewed
    # files. A repeated invocation does not rewrite identical source bytes.
    files+=("$runtime_path" root/usr/share/shadowsocksr/ssrplus-build.json)
    for path in "${files[@]}"; do
        if cmp -s "$scratch/$path" "$package_dir/$path"; then
            case "$path" in
                root/usr/share/shadowsocksr/shadowsocksr.config) chmod 644 "$package_dir/$path" || return 1 ;;
                root/*) [[ "$path" == */ssrplus-build.json ]] || chmod 755 "$package_dir/$path" || return 1 ;;
            esac
            continue
        fi
        temporary=$(mktemp "$package_dir/$path.ssrfix.XXXXXX") || return 1
        if ! cp -p "$scratch/$path" "$temporary" || ! mv -f "$temporary" "$package_dir/$path"; then
            rm -f "$temporary"
            return 1
        fi
    done
    echo "SSR Plus 兼容修复集完成，受保护源码与成品清单均已生成。"
)
