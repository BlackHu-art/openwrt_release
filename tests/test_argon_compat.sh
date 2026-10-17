#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
source "$repo_root/wrt_core/modules/package_source_updates.sh"
temp_base=$(cd "${TMPDIR:-/tmp}" && pwd -P)
test_root=$(mktemp -d "$temp_base/argon-compat.XXXXXX")
cleanup() {
    case "$test_root" in
        "$temp_base"/argon-compat.*) rm -rf -- "$test_root" ;;
        *) echo "Refusing to remove unexpected test directory: $test_root" >&2 ;;
    esac
}
trap cleanup EXIT
fail() { echo "FAIL: $*" >&2; exit 1; }

# Representative conflicting payloads from jerrykuku/luci-theme-argon
# 539e3e1db56b2348c3655615540e45638b797c73 (3.0.0) and
# jerrykuku/luci-app-argon-config 445af53fbee6e00fa6efc0ae33f8b2854df65500.
payloads=(
    root/etc/config/argon
    root/usr/libexec/rpcd/luci.argon
    root/usr/share/luci/menu.d/luci-app-argon-config.json
    htdocs/luci-static/resources/view/argon-config.js
    po/zh_Hans/argon-config.po
)
write_payloads() {
    local package_dir=$1 label=$2 path
    for path in "${payloads[@]}"; do
        mkdir -p "$package_dir/$(dirname "$path")"
        printf '%s\n' "$label" > "$package_dir/$path"
    done
}

# Keep actual Git checkout/replacement behavior; redirect only the remote URL.
legacy_source="$test_root/legacy-source"
mkdir -p "$legacy_source"
printf '%s\n' 'PKG_NAME:=luci-app-argon-config' 'LUCI_DEPENDS:=+luci-theme-argon' \
    '# call BuildPackage' > "$legacy_source/Makefile"
write_payloads "$legacy_source" legacy
git init -q "$legacy_source"
git -C "$legacy_source" -c core.autocrlf=false add .
git -C "$legacy_source" -c user.name=Fixture -c user.email=fixture@example.invalid \
    commit -qm 'Legacy standalone Argon config'
git_retry() {
    git -c "url.file://$legacy_source.insteadOf=https://github.com/jerrykuku/luci-app-argon-config.git" "$@"
}

new_case() {
    BUILD_DIR="$test_root/$1"
    theme_dir="$BUILD_DIR/feeds/luci/themes/luci-theme-argon"
    app_dir="$BUILD_DIR/feeds/luci/applications/luci-app-argon-config"
    mkdir -p "$theme_dir" "$app_dir"
    printf '%s\n' 'PKG_VERSION:=2.3.2' '# call BuildPackage' > "$theme_dir/Makefile"
}

integrate_theme() {
    printf '%s\n' 'PKG_VERSION:=3.0.0' 'LUCI_BASENAME:=argon-config' \
        '# call BuildPackage' > "$theme_dir/Makefile"
    write_payloads "$theme_dir" integrated
    mkdir -p "$theme_dir/root/usr/share/argon" "$theme_dir/compat/luci-app-argon-config"
    printf '%s\n' 'Argon settings are provided by luci-theme-argon.' \
        > "$theme_dir/root/usr/share/argon/config-integrated"
    cp "$legacy_source/Makefile" "$theme_dir/compat/luci-app-argon-config/Makefile"
}

assert_single_owner() {
    local path owners
    for path in "${payloads[@]}"; do
        owners=$(find "$BUILD_DIR/feeds/luci" -type f -path "*/$path" | wc -l)
        [[ "$owners" -eq 1 ]] || fail "Argon payload $path has $owners owners; expected one"
        [[ $(cat "$theme_dir/$path") == integrated ]] || fail "integrated settings changed: $path"
    done
    # OpenWrt scripts/feeds scans Makefiles to depth 5; the empty upstream
    # compatibility package must still be discoverable under its old name.
    [[ -f "$theme_dir/compat/luci-app-argon-config/Makefile" ]] || fail 'compat package lost'
    local recipes
    recipes=$(find "$BUILD_DIR/feeds/luci" -maxdepth 5 -name Makefile | wc -l)
    [[ "$recipes" -eq 2 ]] || fail "expected theme and compat recipes, got $recipes"
}

new_case fresh
integrate_theme
update_argon_config
assert_single_owner
echo 'fresh integrated Argon: PASS'

new_case stale
integrate_theme
cp -R "$legacy_source/root" "$legacy_source/htdocs" "$legacy_source/po" "$app_dir/"
cp "$legacy_source/Makefile" "$app_dir/Makefile"
update_argon_config
assert_single_owner
update_argon_config
assert_single_owner
echo 'stale standalone payload removal and repeated setup: PASS'

new_case legacy
update_argon_config
for path in "${payloads[@]}"; do
    [[ $(cat "$app_dir/$path") == legacy ]] || fail "legacy settings missing: $path"
done
echo 'legacy theme retains standalone settings: PASS'

new_case missing-compat
integrate_theme
rm "$theme_dir/compat/luci-app-argon-config/Makefile"
printf '%s\n' untouched > "$app_dir/keep"
if update_argon_config; then
    fail 'integrated theme without its compatibility recipe was accepted'
fi
[[ $(cat "$app_dir/keep") == untouched ]] || fail 'failed validation changed existing source'
[[ $(cat "$theme_dir/${payloads[0]}") == integrated ]] || fail 'failed validation changed theme'
echo 'missing compatibility recipe rejected before changes: PASS'

new_case missing-theme
rm "$theme_dir/Makefile"
printf '%s\n' untouched > "$app_dir/keep"
if update_argon_config; then
    fail 'missing theme was accepted'
fi
[[ $(cat "$app_dir/keep") == untouched ]] || fail 'missing theme changed existing source'
echo 'missing theme rejected before changes: PASS'

new_case clone-failure
printf '%s\n' untouched > "$app_dir/keep"
git_retry() { return 29; }
if update_argon_config; then
    fail 'standalone source checkout failure was swallowed'
fi
[[ $(cat "$app_dir/keep") == untouched ]] || fail 'failed clone changed existing source'
echo 'legacy checkout failure preserves existing source: PASS'
