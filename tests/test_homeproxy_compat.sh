#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
BASE_PATH="$repo_root/wrt_core"
source "$BASE_PATH/modules/feed_source_fixes.sh"
source "$BASE_PATH/modules/plugin_compat.sh"

temp_base=$(cd "${TMPDIR:-/tmp}" && pwd -P)
test_root=$(mktemp -d "$temp_base/homeproxy-compat.XXXXXX")
cleanup() {
    case "$test_root" in
        "$temp_base"/homeproxy-compat.*)
            [[ -n "$test_root" && "$test_root" != "$temp_base" ]] && rm -rf -- "$test_root"
            ;;
        *) echo "Refusing to remove unexpected test directory: $test_root" >&2 ;;
    esac
}
trap cleanup EXIT

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

fixture_dir="$repo_root/tests/fixtures/homeproxy"
generator_path=root/etc/homeproxy/scripts/generate_client.uc
old_generator_blob=890d23b0642a6b748805513c953782026f59d25e
fixed_generator_blob=050d4e2a8b3b7f2071a0c3bcf723fd717af0437f
patches=(
    homeproxy-7c6ded7-sing-box-1.14.patch
    homeproxy-1a32fca-acl-domains.patch
    homeproxy-10f4244-feature-cache.patch
    homeproxy-routing-cleanup.patch
)

make_package() {
    local package_dir=$1
    mkdir -p "$package_dir/$(dirname "$generator_path")"
    cp "$fixture_dir/Makefile" "$package_dir/Makefile"
    cp "$fixture_dir/generate_client.uc" "$package_dir/$generator_path"
    mkdir -p "$package_dir/htdocs/luci-static/resources/view/homeproxy" \
        "$package_dir/root/etc/init.d" "$package_dir/root/usr/share/rpcd/ucode"
    cp "$fixture_dir/client.js" "$package_dir/htdocs/luci-static/resources/view/homeproxy/client.js"
    cp "$fixture_dir/homeproxy.init" "$package_dir/root/etc/init.d/homeproxy"
    cp "$fixture_dir/luci.homeproxy" "$package_dir/root/usr/share/rpcd/ucode/luci.homeproxy"
    chmod +x "$package_dir/$generator_path"
    chmod +x "$package_dir/root/etc/init.d/homeproxy"
    git init -q "$package_dir"
    git -C "$package_dir" config core.autocrlf false
}

make_fixed_package() {
    local package_dir=$1
    make_package "$package_dir"
    local patch
    for patch in "${patches[@]}"; do
        git -C "$package_dir" apply "$BASE_PATH/patches/$patch"
    done
    [[ $(git hash-object --no-filters "$package_dir/$generator_path") == "$fixed_generator_blob" ]] ||
        fail "the upstream patch no longer produces the independently recorded result"
}

package_snapshot() {
    (
        cd "$1"
        find . -path './.git' -prune -o -type f -print | LC_ALL=C sort |
            while IFS= read -r path; do
                printf '%s ' "$path"
                git hash-object --no-filters "$path"
            done
    )
}

assert_upstream_fixes() {
    local package_dir=$1 blob path
    local manifest=${2:-$fixture_dir/patched-blobs.txt}
    while read -r blob path; do
        [[ $(git hash-object --no-filters "$package_dir/$path") == "$blob" ]] ||
            fail "unexpected patched content: $path (expected $blob, got $(git hash-object --no-filters "$package_dir/$path"))"
    done <"$manifest"
    bash -n "$package_dir/root/etc/init.d/homeproxy"
    bash -n "$package_dir/root/etc/uci-defaults/luci-homeproxy-features"
}

assert_math_dependency() {
    local makefile=$1
    local dependencies
    dependencies=$(awk '
        /^[[:space:]]*#/ { next }
        /^[[:space:]]*LUCI_DEPENDS[[:space:]]*[:+?]?=/ {
            active = 1
            sub(/^[^=]*=/, "")
        }
        active {
            sub(/#.*/, "")
            more = /\\[[:space:]]*$/
            gsub(/\\/, "")
            for (i = 1; i <= NF; i++) print $i
            active = more
        }
    ' "$makefile")
    [[ $(printf '%s\n' "$dependencies" | grep -Fxc '+ucode-mod-math') == 1 ]] ||
        fail "math must appear exactly once in active LUCI_DEPENDS: $makefile"
    local dependency
    for dependency in +sing-box +firewall4 +kmod-nft-tproxy +ucode-mod-digest; do
        printf '%s\n' "$dependencies" | grep -Fxq "$dependency" ||
            fail "existing dependency $dependency was lost: $makefile"
    done
}

expect_rejected_without_changes() {
    local package_dir=$1
    local description=$2
    package_snapshot "$package_dir" >"$test_root/package-before"
    if fix_homeproxy_compat "$package_dir" >"$test_root/rejection.log" 2>&1; then
        fail "$description was accepted"
    fi
    [[ -s "$test_root/rejection.log" ]] || fail "$description did not explain its rejection"
    package_snapshot "$package_dir" >"$test_root/package-after"
    cmp "$test_root/package-before" "$test_root/package-after" ||
        fail "$description partially changed the package"
    [[ -z $(find "$package_dir" -name '*.rej' -o -name '*.orig') ]] ||
        fail "$description left patch rejection or backup files"
}

[[ $(git hash-object --no-filters "$fixture_dir/generate_client.uc") == "$old_generator_blob" ]] ||
    fail "the offline fixture no longer matches upstream 98a6ad9"
declare -F fix_homeproxy_compat >/dev/null || fail "fix_homeproxy_compat is not defined"

# Current upstream has absorbed part of PR #673. Accept every subset of the
# remaining patches without restoring removed UI options or changing VPN routing.
latest_patches=(homeproxy-fadaa676-sing-box-1.14.patch "${patches[@]:1}")
for mask in {0..15}; do
    package_dir="$test_root/latest-$mask"
    make_package "$package_dir"
    cp "$fixture_dir/fadaa676/generate_client.uc" "$package_dir/$generator_path"
    cp "$fixture_dir/fadaa676/client.js" "$package_dir/htdocs/luci-static/resources/view/homeproxy/client.js"
    for index in 0 1 2 3; do
        if (( mask & (1 << index) )); then
            git -C "$package_dir" apply "$BASE_PATH/patches/${latest_patches[$index]}"
        fi
    done
    fix_homeproxy_compat "$package_dir"
    assert_upstream_fixes "$package_dir" "$fixture_dir/fadaa676/patched-blobs.txt"
    assert_math_dependency "$package_dir/Makefile"
done
package_snapshot "$package_dir" >"$test_root/latest-before"
fix_homeproxy_compat "$package_dir"
package_snapshot "$package_dir" >"$test_root/latest-after"
cmp "$test_root/latest-before" "$test_root/latest-after" || fail 'repeat changed latest upstream'

package_dir="$test_root/latest-drift"
make_package "$package_dir"
cp "$fixture_dir/fadaa676/generate_client.uc" "$package_dir/$generator_path"
sed -i "s/action: 'sniff'/action: 'unknown-sniff'/" "$package_dir/$generator_path"
expect_rejected_without_changes "$package_dir" 'unknown latest generator drift'

package_dir="$test_root/latest-partial-compat"
make_package "$package_dir"
cp "$fixture_dir/fadaa676/generate_client.uc" "$package_dir/$generator_path"
sed -i '/disable_expire: strToBool(dns_disable_cache_expire),/d' "$package_dir/$generator_path"
expect_rejected_without_changes "$package_dir" 'partially applied latest compatibility fix'

# Apply the selected fixes without the unrelated VPN interface-selection change.
package_dir="$test_root/old"
make_package "$package_dir"
fix_homeproxy_compat "$package_dir"
[[ $(git hash-object --no-filters "$package_dir/$generator_path") == "$fixed_generator_blob" ]] ||
    fail "old HomeProxy did not receive the expected compatibility patch"
assert_math_dependency "$package_dir/Makefile"
assert_upstream_fixes "$package_dir"

# Running the build preparation twice must not duplicate dependencies or rules.
cp "$package_dir/Makefile" "$test_root/fixed-makefile"
cp "$package_dir/$generator_path" "$test_root/fixed-generator"
package_snapshot "$package_dir" >"$test_root/all-fixed-before"
fix_homeproxy_compat "$package_dir"
cmp "$test_root/fixed-makefile" "$package_dir/Makefile" || fail 'repeat changed dependencies'
cmp "$test_root/fixed-generator" "$package_dir/$generator_path" || fail 'repeat changed generator'
package_snapshot "$package_dir" >"$test_root/all-fixed-after"
cmp "$test_root/all-fixed-before" "$test_root/all-fixed-after" || fail 'repeat changed patched files'

# Upstream can land any subset of the independent fixes before a fresh clone.
for mask in {1..14}; do
    package_dir="$test_root/partial-$mask"
    make_package "$package_dir"
    for index in 0 1 2 3; do
        if (( mask & (1 << index) )); then
            git -C "$package_dir" apply "$BASE_PATH/patches/${patches[$index]}"
        fi
    done
    fix_homeproxy_compat "$package_dir"
    assert_upstream_fixes "$package_dir"
    assert_math_dependency "$package_dir/Makefile"
done

# A generator already fixed by upstream needs only the missing dependency.
package_dir="$test_root/already-fixed"
make_fixed_package "$package_dir"
fix_homeproxy_compat "$package_dir"
assert_math_dependency "$package_dir/Makefile"
cmp "$test_root/fixed-generator" "$package_dir/$generator_path" ||
    fail 'already-fixed upstream generator was changed'

# Preserve a fully fixed upstream Makefile byte-for-byte, including formatting.
package_dir="$test_root/already-fixed-with-math"
make_fixed_package "$package_dir"
sed -i 's/+ucode-mod-digest/+ucode-mod-math \\\n\t+ucode-mod-digest/' "$package_dir/Makefile"
cp "$package_dir/Makefile" "$test_root/upstream-fixed-makefile"
fix_homeproxy_compat "$package_dir"
cmp "$test_root/upstream-fixed-makefile" "$package_dir/Makefile" ||
    fail 'already-present math dependency was modified or duplicated'
assert_math_dependency "$package_dir/Makefile"

# A comment mentioning math is not a dependency, for either declaration style.
for layout in single-line multiline; do
    package_dir="$test_root/comment-$layout"
    make_fixed_package "$package_dir"
    if [[ $layout == single-line ]]; then
        printf '%s\n' '# +ucode-mod-math is not installed' \
            'LUCI_DEPENDS:=+sing-box +firewall4 +kmod-nft-tproxy +ucode-mod-digest # +ucode-mod-math' >"$package_dir/Makefile"
    else
        cat >"$package_dir/Makefile" <<'EOF'
# +ucode-mod-math is not installed
LUCI_DEPENDS:= \
    +sing-box \
    +firewall4 \
    +kmod-nft-tproxy \
    +ucode-mod-digest # +ucode-mod-math
EOF
    fi
    fix_homeproxy_compat "$package_dir"
    assert_math_dependency "$package_dir/Makefile"
done

# Unknown generator changes must fail before adding math or applying any hunks.
package_dir="$test_root/drift"
make_package "$package_dir"
sed -i 's/sniff: true,/sniff: false,/' "$package_dir/$generator_path"
expect_rejected_without_changes "$package_dir" 'unknown generator drift'

# Removing the dependency declaration must not leave a patched generator behind.
package_dir="$test_root/no-dependencies"
make_package "$package_dir"
sed -i '/^LUCI_DEPENDS:=/,+4d' "$package_dir/Makefile"
expect_rejected_without_changes "$package_dir" 'missing LUCI_DEPENDS'

# Later patch failures must be detected before even the first patch is applied.
package_dir="$test_root/acl-drift"
make_package "$package_dir"
sed -i "s/callWriteDomainList('proxy_list', value)/callWriteDomainList('renamed_list', value)/" \
    "$package_dir/htdocs/luci-static/resources/view/homeproxy/client.js"
expect_rejected_without_changes "$package_dir" 'ACL source drift'

package_dir="$test_root/cache-drift"
make_package "$package_dir"
sed -i 's@/usr/bin/sing-box version@/usr/bin/sing-box changed-version@' \
    "$package_dir/root/usr/share/rpcd/ucode/luci.homeproxy"
expect_rejected_without_changes "$package_dir" 'feature RPC source drift'

package_dir="$test_root/partial-cache"
make_package "$package_dir"
cp "$test_root/old/root/etc/homeproxy/scripts/singbox_features.uc" \
    "$package_dir/root/etc/homeproxy/scripts/singbox_features.uc"
expect_rejected_without_changes "$package_dir" 'partially installed cache patch'

saved_base_path=$BASE_PATH
BASE_PATH="$test_root/missing-patch-base"
mkdir -p "$BASE_PATH/patches"
cp "$saved_base_path/patches/${patches[0]}" "$BASE_PATH/patches/"
cp "$saved_base_path/patches/${patches[1]}" "$BASE_PATH/patches/"
cp "$saved_base_path/patches/${latest_patches[0]}" "$BASE_PATH/patches/"
package_dir="$test_root/missing-cache-patch"
make_package "$package_dir"
expect_rejected_without_changes "$package_dir" 'missing feature-cache patch'
BASE_PATH=$saved_base_path

# The production updater now consumes the source staged by the managed feed.
# Keep both supported upstream layouts and reject drift without another fetch.
get_custom_feed_worktree_dir() {
    printf '%s\n' "$feed_dir"
}
git_retry() { fail 'managed HomeProxy attempted an external clone'; }

feed_dir="$test_root/feed-old"
package_dir="$feed_dir/luci-app-homeproxy"
make_package "$package_dir"
update_homeproxy
[[ $(git hash-object --no-filters "$package_dir/$generator_path") == "$fixed_generator_blob" ]] ||
    fail 'update_homeproxy did not repair the staged old source'
assert_math_dependency "$package_dir/Makefile"
assert_upstream_fixes "$package_dir"

# An incompatible staged source must propagate failure even in an if context,
# without partially applying patches or changing its dependency declaration.
feed_dir="$test_root/feed-drift"
package_dir="$feed_dir/luci-app-homeproxy"
make_package "$package_dir"
sed -i 's/sniff: true,/sniff: false,/' "$package_dir/$generator_path"
package_snapshot "$package_dir" > "$test_root/update-before"
if (update_homeproxy) >"$test_root/update-rejection.log" 2>&1; then
    fail 'update_homeproxy swallowed compatibility failure'
fi
package_snapshot "$package_dir" > "$test_root/update-after"
cmp "$test_root/update-before" "$test_root/update-after" ||
    fail 'failed update modified staged source'

# Exercise the same production entrypoint for the locked fadaa676 layout.
feed_dir="$test_root/feed-latest"
package_dir="$feed_dir/luci-app-homeproxy"
make_package "$package_dir"
cp "$fixture_dir/fadaa676/generate_client.uc" "$package_dir/$generator_path"
cp "$fixture_dir/fadaa676/client.js" "$package_dir/htdocs/luci-static/resources/view/homeproxy/client.js"
update_homeproxy
assert_upstream_fixes "$package_dir" "$fixture_dir/fadaa676/patched-blobs.txt"
assert_math_dependency "$package_dir/Makefile"

# Stop before any unrelated build helper if the HomeProxy update fails.
stage_marker="$test_root/next-stage-called"
status=0
(
    source "$repo_root/wrt_core/update.sh"
    ensure_libffi_source() { :; }
    update_homeproxy() { return 1; }
    fix_default_set() { printf '%s\n' unexpected >"$stage_marker"; exit 77; }
    stage_pre_install_source_fixes
) || status=$?
[[ $status -eq 1 ]] || fail "HomeProxy stage failure returned $status instead of 1"
[[ ! -e "$stage_marker" ]] || fail 'source-fix stage continued after HomeProxy failure'

echo 'HomeProxy compatibility: PASS'
