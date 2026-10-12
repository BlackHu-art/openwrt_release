#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
BASE_PATH="$repo_root/wrt_core"
source "$BASE_PATH/modules/feed_source_fixes.sh"

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
fixed_generator_blob=1fbe424744bd48f1c5d2af6a571d77a6697825d8

make_package() {
    local package_dir=$1
    mkdir -p "$package_dir/$(dirname "$generator_path")"
    cp "$fixture_dir/Makefile" "$package_dir/Makefile"
    cp "$fixture_dir/generate_client.uc" "$package_dir/$generator_path"
    chmod +x "$package_dir/$generator_path"
    git init -q "$package_dir"
    git -C "$package_dir" config core.autocrlf false
}

make_fixed_package() {
    local package_dir=$1
    make_package "$package_dir"
    git -C "$package_dir" apply "$BASE_PATH/patches/homeproxy-7c6ded7-sing-box-1.14.patch"
    [[ $(git hash-object --no-filters "$package_dir/$generator_path") == "$fixed_generator_blob" ]] ||
        fail "the upstream patch no longer produces the independently recorded result"
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
    cp "$package_dir/Makefile" "$test_root/makefile-before"
    cp "$package_dir/$generator_path" "$test_root/generator-before"
    if fix_homeproxy_compat "$package_dir" >"$test_root/rejection.log" 2>&1; then
        fail "$description was accepted"
    fi
    [[ -s "$test_root/rejection.log" ]] || fail "$description did not explain its rejection"
    cmp "$test_root/makefile-before" "$package_dir/Makefile" ||
        fail "$description partially changed dependencies"
    cmp "$test_root/generator-before" "$package_dir/$generator_path" ||
        fail "$description partially changed the generator"
    [[ -z $(find "$package_dir" -name '*.rej' -o -name '*.orig') ]] ||
        fail "$description left patch rejection or backup files"
}

[[ $(git hash-object --no-filters "$fixture_dir/generate_client.uc") == "$old_generator_blob" ]] ||
    fail "the offline fixture no longer matches upstream 98a6ad9"
declare -F fix_homeproxy_compat >/dev/null || fail "fix_homeproxy_compat is not defined"

# A real old generator must receive exactly the first upstream fix, without
# including the unrelated VPN interface-selection change from the second one.
package_dir="$test_root/old"
make_package "$package_dir"
fix_homeproxy_compat "$package_dir"
[[ $(git hash-object --no-filters "$package_dir/$generator_path") == "$fixed_generator_blob" ]] ||
    fail "old HomeProxy did not receive the expected compatibility patch"
assert_math_dependency "$package_dir/Makefile"

# Running the build preparation twice must not duplicate dependencies or rules.
cp "$package_dir/Makefile" "$test_root/fixed-makefile"
cp "$package_dir/$generator_path" "$test_root/fixed-generator"
fix_homeproxy_compat "$package_dir"
cmp "$test_root/fixed-makefile" "$package_dir/Makefile" || fail 'repeat changed dependencies'
cmp "$test_root/fixed-generator" "$package_dir/$generator_path" || fail 'repeat changed generator'

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

# Replace only the network transport; exercise the real clone and update helper.
local_upstream="$test_root/upstream"
make_package "$local_upstream"
git -C "$local_upstream" config user.name 'HomeProxy compatibility test'
git -C "$local_upstream" config user.email 'homeproxy-test@example.invalid'
git -C "$local_upstream" add Makefile "$generator_path"
git -C "$local_upstream" commit -qm 'old upstream fixture'

feed_dir="$test_root/feed"
get_custom_feed_worktree_dir() {
    printf '%s\n' "$feed_dir"
}
git_retry() {
    [[ $# -eq 5 && $1 == clone && $2 == --depth && $3 == 1 &&
       $4 == https://github.com/immortalwrt/homeproxy.git ]] ||
        fail 'update_homeproxy changed the expected upstream clone request'
    git -c core.autocrlf=false clone -q --depth 1 "file://$local_upstream" "$5"
    git -C "$5" config core.autocrlf false
}

mkdir -p "$feed_dir/luci-app-homeproxy"
printf '%s\n' stale >"$feed_dir/luci-app-homeproxy/stale"
update_homeproxy
package_dir="$feed_dir/luci-app-homeproxy"
[[ ! -e "$package_dir/stale" ]] || fail 'update retained files from the old checkout'
[[ $(git hash-object --no-filters "$package_dir/$generator_path") == "$fixed_generator_blob" ]] ||
    fail 'update_homeproxy did not fix the newly cloned source'
assert_math_dependency "$package_dir/Makefile"

# A rejected fresh clone must propagate out of update_homeproxy, even when the
# caller uses an if statement (where Bash would otherwise suppress errexit).
sed -i 's/sniff: true,/sniff: false,/' "$local_upstream/$generator_path"
git -C "$local_upstream" add "$generator_path"
git -C "$local_upstream" commit -qm 'upstream incompatible drift'
if (update_homeproxy) >"$test_root/update-rejection.log" 2>&1; then
    fail 'update_homeproxy swallowed compatibility failure'
fi
cmp "$local_upstream/$generator_path" "$package_dir/$generator_path" ||
    fail 'failed update partially patched the fresh clone'
cmp "$fixture_dir/Makefile" "$package_dir/Makefile" ||
    fail 'failed update partially changed dependencies'

# Stop before any unrelated build helper if the HomeProxy update fails.
stage_marker="$test_root/next-stage-called"
status=0
(
    source "$repo_root/wrt_core/update.sh"
    update_homeproxy() { return 1; }
    fix_default_set() { printf '%s\n' unexpected >"$stage_marker"; exit 77; }
    stage_pre_install_source_fixes
) || status=$?
[[ $status -eq 1 ]] || fail "HomeProxy stage failure returned $status instead of 1"
[[ ! -e "$stage_marker" ]] || fail 'source-fix stage continued after HomeProxy failure'

echo 'HomeProxy compatibility: PASS'
