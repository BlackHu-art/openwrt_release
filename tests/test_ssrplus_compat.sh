#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
BASE_PATH="$repo_root/wrt_core"
source "$BASE_PATH/modules/plugin_compat.sh"
source_table="$BASE_PATH/compat/ssrplus/source-files.tsv"
patch_list="$BASE_PATH/compat/ssrplus/patches.list"
runtime_source="$BASE_PATH/compat/ssrplus/runtime.sh"
runtime_path=root/usr/share/shadowsocksr/ssrp-runtime.sh
manifest_path=root/usr/share/shadowsocksr/ssrplus-build.json
upstream_commit=2abdc9aa9e19607774dc9789709212b70b8607c6
temp_base=$(cd "${TMPDIR:-/tmp}" && pwd -P)
test_root=$(mktemp -d "$temp_base/ssrplus-compat.XXXXXX")
cleanup() {
    case "$test_root" in
        "$temp_base"/ssrplus-compat.*) rm -rf -- "$test_root" ;;
        *) echo "Unexpected test path: $test_root" >&2 ;;
    esac
}
trap cleanup EXIT
fail() { echo "FAIL: $*" >&2; exit 1; }

# Independent upstream Git blobs: never infer an accepted baseline from the
# patch under test or silently tolerate changes outside its context lines.
declare -A reviewed_blobs=() fixture_paths=()
while read -r blob path; do
    reviewed_blobs["$path"]=$blob
done <<'BLOBS'
1d5c32973355320958fd9ced04599a7e5350e7d3 root/etc/init.d/shadowsocksr
f4ade91b08e3cc350a1100e99cf96eba0008706f root/usr/share/shadowsocksr/gfw2ipset.sh
34d13dc89e5c013e3213f02c37d8dc8d698d3a4c root/usr/share/shadowsocksr/update.lua
074d002cf612cc18357529dcb24c9cd5b93a9593 root/usr/bin/ssr-rules
f88a83d10027d2854e3464d5d70cc959e0259b2d root/usr/share/shadowsocksr/subscribe.lua
51f9efc400b1271528f5c442951474326c620dd9 root/usr/bin/ssr-monitor
9424cfac716f7b265b7e89cb75ce88106d0a7cfd root/usr/share/shadowsocksr/ssrplusupdate.sh
5a2a3709032f791fb8d6bd2822576fe7d0e76dbd root/usr/bin/ssr-switch
41a65caeda830cd9d032b8d8595c0d045b041805 Makefile
5f54eb9974052df4f437afd0c45dc5d2f3337c4a root/etc/uci-defaults/luci-ssr-plus
ded6977f352d1c10da96b4bc2fdb9b4cac2c36d1 root/usr/share/shadowsocksr/shadowsocksr.config
e226697bced19dab2481fd920f3cad219fa0c666 root/usr/share/shadowsocksr/gen_config.lua
BLOBS
source_paths=()
while read -r blob path fixture; do
    [[ -n "$path" && -n "$fixture" && ${reviewed_blobs[$path]:-} == "$blob" ]] ||
        fail "unreviewed source-table entry: $path"
    [[ -z ${fixture_paths[$path]:-} ]] || fail "duplicate protected source: $path"
    fixture_paths["$path"]="$repo_root/tests/fixtures/$fixture"
    [[ $(git hash-object --no-filters "${fixture_paths[$path]}") == "$blob" ]] ||
        fail "fixture differs from reviewed upstream: $path"
    source_paths+=("$path")
done < "$source_table"
[[ ${#source_paths[@]} -eq 12 ]] || fail 'source table must protect twelve reviewed files including initialization assets and the core generator'
declare -F fix_ssrplus_compat >/dev/null ||
    fail "fix_ssrplus_compat is not defined by modules/plugin_compat.sh"

mapfile -t patches < "$patch_list"
expected_patches=(ssrplus-startup-lock.patch ssrplus-dns-transaction.patch ssrplus-updater-validation.patch
    ssrplus-persistence.patch ssrplus-availability.patch ssrplus-subscription.patch
    ssrplus-monitor-scheduler.patch ssrplus-persistence-lifecycle.patch ssrplus-package.patch
    ssrplus-dns-forwarding.patch ssrplus-custom-ports.patch ssrplus-release-r5.patch
    ssrplus-firstboot.patch ssrplus-release-r6.patch
    ssrplus-initialization-order.patch ssrplus-release-r7.patch
    ssrplus-subscription-auto.patch ssrplus-ss-parser.patch ssrplus-release-r8.patch
    ssrplus-transport-config.patch ssrplus-release-r9.patch
    ssrplus-ss-password.patch ssrplus-release-r10.patch
    ssrplus-node-references.patch ssrplus-release-r11.patch)
[[ ${patches[*]} == "${expected_patches[*]}" ]] || fail 'complete SSR dependency order is missing or changed'
independent=(ssrplus-startup-lock.patch ssrplus-dns-transaction.patch ssrplus-persistence.patch)
for patch_file in "${patches[@]}"; do
    [[ -s "$BASE_PATH/patches/$patch_file" ]] || fail "missing SSR compatibility patch: $patch_file"
done

snapshot() {
    (cd "$1"; find . -path './.git' -prune -o -type f -print |
        LC_ALL=C sort | while read -r path; do sha256sum "$path"; stat -c '%a' "$path"; done)
}
make_package() {
    local parent=$1 path
    local package="$parent/sparse-feed/luci-app-ssr-plus"
    for path in "${source_paths[@]}"; do
        mkdir -p "$package/$(dirname "$path")"
        cp "${fixture_paths[$path]}" "$package/$path"
        # Raw fixture checkout modes are not installed-program modes.
        case "$path" in
            root/*/shadowsocksr.config) chmod 644 "$package/$path" ;;
            root/*) chmod 755 "$package/$path" ;;
        esac
    done
    # Production sparse transfer retains a parent repository but no package .git.
    git init -q "$parent"
    git -C "$parent" config core.autocrlf false
    printf '%s\n' "$package"
}
direct_patch() {
    local parent=$1
    shift
    git -C "$parent" apply --directory=sparse-feed/luci-app-ssr-plus "$@"
}
assert_manifest() {
    local package=$1 expected_commit=${2:-$upstream_commit}
    python - "$package" "$source_table" "$patch_list" "$BASE_PATH/patches" "$expected_commit" <<'PY' || return 1
import hashlib
import json
from pathlib import Path
import sys

package, table, patch_list, patch_dir = map(Path, sys.argv[1:5])
manifest = json.loads((package / "root/usr/share/shadowsocksr/ssrplus-build.json").read_text(encoding="utf-8"))
assert manifest["source_commit"] == sys.argv[5], "wrong source commit in embedded manifest"
assert manifest["repair_version"] == "190-r11", "wrong repair version"
patches = patch_list.read_text().splitlines()
expected = {name: hashlib.sha256((patch_dir / name).read_bytes()).hexdigest() for name in patches}
assert manifest["patches"] == expected, "patch manifest omitted or changed an extension"
paths = {"/" + line.split()[1][5:] for line in table.read_text().splitlines()
         if line.split()[1].startswith("root/")}
paths.add("/usr/share/shadowsocksr/ssrp-runtime.sh")
assert set(manifest["files"]) == paths, "protected-file manifest omitted a reviewed program"
for target in paths:
    actual = package / "root" / target.lstrip("/")
    expected = manifest["files"][target]
    assert expected["sha256"] == hashlib.sha256(actual.read_bytes()).hexdigest(), target
    mode = "0644" if target == "/usr/share/shadowsocksr/shadowsocksr.config" else "0755"
    assert expected["mode"] == mode, "manifest lost installed mode: " + target
PY
    # Native Windows stat cannot prove POSIX executable modes. Shell stat above
    # verifies install/chmod; the Linux artifact gate verifies actual rootfs modes.
    case $(uname -s) in
        MINGW*|MSYS*|CYGWIN*) ;;
        *) python "$BASE_PATH/ssrplus_verify.py" rootfs --manifest "$package/$manifest_path" \
               --root "$package/root" >/dev/null ;;
    esac
}
normalize_counter=0
assert_fully_patched() {
    local parent=$1 package=$2 patch_file path normalized i
    normalize_counter=$((normalize_counter + 1))
    normalized="$test_root/normalize-$normalize_counter"
    git init -q "$normalized"
    git -C "$normalized" config core.autocrlf false
    for path in "${source_paths[@]}"; do
        mkdir -p "$normalized/$(dirname "$path")"
        cp "$package/$path" "$normalized/$path"
    done
    # Dependent extensions must be reversed in order in a separate copy.
    # Independent reverse checks against final source would reject valid output.
    for ((i=${#patches[@]}-1; i>=0; i--)); do
        patch_file=${patches[$i]}
        git -C "$normalized" apply --reverse --check "$BASE_PATH/patches/$patch_file" ||
            fail "complete result is missing dependent patch: $patch_file"
        git -C "$normalized" apply --reverse "$BASE_PATH/patches/$patch_file"
    done
    for path in "${source_paths[@]}"; do
        [[ $(git hash-object --no-filters "$normalized/$path") == "${reviewed_blobs[$path]}" ]] ||
            fail "composed result did not normalize to official source: $path"
    done
    grep -qx 'PKG_VERSION:=190' "$package/Makefile" || fail 'package base version changed unexpectedly'
    grep -qx 'PKG_RELEASE:=11' "$package/Makefile" || fail 'repair release marker is missing'
    grep -Fq 'Local repair set: SSR-20261021' "$package/Makefile" || fail 'local repair identity is missing'
    grep -Fq '+flock' "$package/Makefile" || fail 'persistent-lock dependency was not declared'
    cmp "$runtime_source" "$package/$runtime_path" || fail 'installed runtime helper differs from the reviewed project source'
    [[ $(stat -c '%a' "$package/$runtime_path") == 755 ]] || fail 'runtime helper is not executable'
    for path in "${source_paths[@]}" "$runtime_path"; do
        case "$path" in Makefile|*.lua|*.config) ;; *) bash -n "$package/$path" ;; esac
    done
    assert_manifest "$package"
}
assert_rejection_preserves_source() {
    local package=$1 label=$2
    snapshot "$package" > "$test_root/before"
    if fix_ssrplus_compat "$package" > "$test_root/rejection.log" 2>&1; then
        fail "$label was accepted"
    fi
    [[ -s "$test_root/rejection.log" ]] || fail "$label was rejected without a diagnostic"
    snapshot "$package" > "$test_root/after"
    cmp "$test_root/before" "$test_root/after" || fail "$label caused a partial source modification"
}

# Every already-applied subset must converge to the same complete patch set.
# A no-op helper or git apply silently skipping nested paths fails reverse checks.
# Default covers all legacy states. A focused rerun after a dependent patch
# changes can select e.g. SSRP_COMPAT_MASKS=0; the full current set still runs.
read -r -a legacy_masks <<< "${SSRP_COMPAT_MASKS:-0 1 2 3 4 5 6 7}"
for mask in "${legacy_masks[@]}"; do
    case "$mask" in [0-7]) ;; *) fail "unknown legacy patch subset: $mask" ;; esac
    parent="$test_root/subset-$mask"
    package=$(make_package "$parent")
    for index in 0 1 2; do
        if (( mask & (1 << index) )); then
            direct_patch "$parent" "$BASE_PATH/patches/${independent[$index]}"
        fi
    done
    if ! fix_ssrplus_compat "$package" > "$test_root/apply-$mask.log" 2>&1; then
        cat "$test_root/apply-$mask.log" >&2
        fail "subset $mask compatibility application failed"
    fi
    assert_fully_patched "$parent" "$package"
    snapshot "$package" > "$test_root/before"
    if ! fix_ssrplus_compat "$package" > "$test_root/repeat-$mask.log" 2>&1; then
        cat "$test_root/repeat-$mask.log" >&2
        fail "subset $mask repeat application failed"
    fi
    snapshot "$package" > "$test_root/after"
    cmp "$test_root/before" "$test_root/after" || fail "subset $mask was not idempotent"
done
# r4/r5 manifests protected the original eight programs plus the runtime; r6
# added the hook/template targets and their mixed modes with fourteen patches.
# Complete r7/r8 retain eleven targets with sixteen/nineteen published patches;
# complete r9/r10 protect the generator as their twelfth target with twenty-one/
# twenty-three original patches.
for legacy_release in 4 5 6 7 8 9 10; do
    parent="$test_root/complete-r$legacy_release-existing"
    package=$(make_package "$parent")
    legacy_count=9
    [[ $legacy_release != 5 ]] || legacy_count=12
    [[ $legacy_release != 6 ]] || legacy_count=14
    [[ $legacy_release != 7 ]] || legacy_count=16
    [[ $legacy_release != 8 ]] || legacy_count=19
    [[ $legacy_release != 9 ]] || legacy_count=21
    [[ $legacy_release != 10 ]] || legacy_count=23
    legacy_sources=9
    [[ $legacy_release != 6 ]] || legacy_sources=11
    [[ $legacy_release != 7 ]] || legacy_sources=11
    [[ $legacy_release != 8 ]] || legacy_sources=11
    [[ $legacy_release != 9 ]] || legacy_sources=12
    [[ $legacy_release != 10 ]] || legacy_sources=12
    legacy_patches=("${patches[@]:0:$legacy_count}")
    manifest_args=()
    for patch_file in "${legacy_patches[@]}"; do
        direct_patch "$parent" "$BASE_PATH/patches/$patch_file"
        manifest_args+=(--patch "$BASE_PATH/patches/$patch_file")
    done
    install -m 755 "$runtime_source" "$package/$runtime_path"
    for path in "${source_paths[@]:0:$legacy_sources}"; do
        [[ $path != root/* ]] || manifest_args+=(--file "/${path#root/}")
    done
    legacy_mode_args=()
    if (( legacy_release >= 6 )); then
        legacy_mode_args+=(--file-mode-override /usr/share/shadowsocksr/shadowsocksr.config=0644)
    fi
    MSYS2_ARG_CONV_EXCL="${MSYS2_ARG_CONV_EXCL:+$MSYS2_ARG_CONV_EXCL;}/etc/;/usr/" \
        python "$BASE_PATH/ssrplus_verify.py" manifest --root "$package/root" \
            --output "$package/$manifest_path" --source-commit "$upstream_commit" \
            --repair-version "190-r$legacy_release" --file-mode 0755 "${legacy_mode_args[@]}" "${manifest_args[@]}" \
            --file /usr/share/shadowsocksr/ssrp-runtime.sh
    python - "$package/$manifest_path" "$legacy_count" "$legacy_sources" "$legacy_release" <<'PY'
import json
from pathlib import Path
import sys
manifest = json.loads(Path(sys.argv[1]).read_text())
assert manifest["repair_version"] == "190-r" + sys.argv[4], "legacy repair identity changed"
assert len(manifest["files"]) == int(sys.argv[3]), "legacy installed target count changed"
assert len(manifest["patches"]) == int(sys.argv[2])
if int(sys.argv[2]) < 14:
    assert "/etc/uci-defaults/luci-ssr-plus" not in manifest["files"]
    assert "/usr/share/shadowsocksr/shadowsocksr.config" not in manifest["files"]
else:
    assert manifest["files"]["/etc/uci-defaults/luci-ssr-plus"]["mode"] == "0755"
    assert manifest["files"]["/usr/share/shadowsocksr/shadowsocksr.config"]["mode"] == "0644"
if int(sys.argv[4]) < 9:
    assert "/usr/share/shadowsocksr/gen_config.lua" not in manifest["files"]
else:
    assert manifest["files"]["/usr/share/shadowsocksr/gen_config.lua"]["mode"] == "0755"
PY
    grep -qx "PKG_RELEASE:=$legacy_release" "$package/Makefile" || fail 'wrong legacy upgrade fixture'
    fix_ssrplus_compat "$package" > "$test_root/r$legacy_release-upgrade.log"
    assert_fully_patched "$parent" "$package"
    snapshot "$package" > "$test_root/before"
    fix_ssrplus_compat "$package" > "$test_root/r$legacy_release-repeat.log"
    snapshot "$package" > "$test_root/after"
    cmp "$test_root/before" "$test_root/after" || fail "r$legacy_release upgrade was not idempotent"
    echo "SSR complete r$legacy_release source and original manifest upgrade to r11: PASS"
done

# The complete dependent patch set may also be present before this helper runs.
parent="$test_root/complete-existing"
package=$(make_package "$parent")
for patch_file in "${patches[@]}"; do direct_patch "$parent" "$BASE_PATH/patches/$patch_file"; done
fix_ssrplus_compat "$package" > "$test_root/complete-apply.log"
assert_fully_patched "$parent" "$package"
snapshot "$package" > "$test_root/before"
fix_ssrplus_compat "$package" > "$test_root/complete-repeat.log"
snapshot "$package" > "$test_root/after"
cmp "$test_root/before" "$test_root/after" || fail 'complete dependent patch set was not idempotent'
chmod 644 "$package/$runtime_path"
fix_ssrplus_compat "$package" > "$test_root/repair-mode.log"
[[ $(stat -c '%a' "$package/$runtime_path") == 755 ]] || fail 'unchanged runtime bytes kept a non-executable mode'
template_path=root/usr/share/shadowsocksr/shadowsocksr.config
chmod 755 "$package/$template_path"
fix_ssrplus_compat "$package" > "$test_root/repair-template-mode.log"
[[ $(stat -c '%a' "$package/$template_path") == 644 ]] || fail 'unchanged template bytes kept an executable mode'
printf 'SSR legacy subsets (%s), complete dependent patch set, version/modes and idempotence: PASS\n' "${legacy_masks[*]}"

# The second patch can reject any of its source files. Preflight must happen
# before the startup patch writes its otherwise-compatible init script.
for target in "${source_paths[@]}"; do
    parent="$test_root/drift-${target##*/}"
    package=$(make_package "$parent")
    printf '\n# unreviewed upstream addition outside patch context\n' >> "$package/$target"
    assert_rejection_preserves_source "$package" "unknown upstream $target"
done

# A partly fixed package remains untouched if a different file has drifted.
parent="$test_root/partial-drift"
package=$(make_package "$parent")
direct_patch "$parent" "$BASE_PATH/patches/ssrplus-startup-lock.patch"
printf '%s\n' 'unrecognized replacement source' > "$package/root/usr/share/shadowsocksr/update.lua"
assert_rejection_preserves_source "$package" "partly patched source with incompatible update.lua"
echo "SSR incompatible-source rejection without partial changes: PASS"

# Whole independent patches may already be installed. An incomplete patch or
# an edited helper is not such a subset, and must leave the package untouched.
parent="$test_root/incomplete-dns-patch"
package=$(make_package "$parent")
direct_patch "$parent" "$BASE_PATH/patches/ssrplus-dns-transaction.patch"
cp "${fixture_paths[root/usr/share/shadowsocksr/gfw2ipset.sh]}" "$package/root/usr/share/shadowsocksr/gfw2ipset.sh"
assert_rejection_preserves_source "$package" 'DNS patch missing its generator changes'
parent="$test_root/incomplete-persistence-patch"
package=$(make_package "$parent")
direct_patch "$parent" "$BASE_PATH/patches/ssrplus-persistence.patch"
python - "$package/root/usr/bin/ssr-rules" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
assert 'persist_nftables_rules || exit 1' in text
path.write_text(text.replace('persist_nftables_rules || exit 1', 'persist_nftables_rules', 1),
                encoding="utf-8", newline="\n")
PY
assert_rejection_preserves_source "$package" 'persistence patch missing a failure-propagation hunk'
parent="$test_root/unknown-helper"
package=$(make_package "$parent")
printf 'unknown preexisting helper\n' >"$package/$runtime_path"
assert_rejection_preserves_source "$package" 'unknown preexisting DNS helper'
parent="$test_root/edited-helper"
package=$(make_package "$parent")
fix_ssrplus_compat "$package" >"$test_root/edited-helper-apply.log"
printf '\n# unreviewed helper change\n' >>"$package/$runtime_path"
assert_rejection_preserves_source "$package" 'changed installed DNS helper'

# Remove one required artifact from an otherwise complete toolset. This proves
# each specific missing input rejects, rather than always failing on an earlier
# missing verifier or manifest before reaching the artifact named by the test.
make_toolset() {
    local destination=$1 patch_file
    mkdir -p "$destination/patches" "$destination/compat/ssrplus"
    cp "$BASE_PATH/ssrplus_verify.py" "$destination/ssrplus_verify.py"
    cp "$source_table" "$patch_list" "$runtime_source" "$destination/compat/ssrplus/"
    for patch_file in "${patches[@]}"; do cp "$BASE_PATH/patches/$patch_file" "$destination/patches/"; done
}
original_base_path=$BASE_PATH
for missing in "patches/${patches[${#patches[@]}-1]}" compat/ssrplus/runtime.sh ssrplus_verify.py \
               compat/ssrplus/patches.list compat/ssrplus/source-files.tsv; do
    parent="$test_root/missing-${missing##*/}"
    package=$(make_package "$parent")
    tools="$test_root/tools-${missing##*/}"
    make_toolset "$tools"
    rm -f "$tools/$missing"
    BASE_PATH=$tools
    assert_rejection_preserves_source "$package" "missing reviewed artifact $missing"
    BASE_PATH=$original_base_path
done
parent="$test_root/missing-source"
package=$(make_package "$parent")
rm -f "$package/root/usr/bin/ssr-monitor"
assert_rejection_preserves_source "$package" 'missing protected source program'
parent="$test_root/invalid-source-commit"
package=$(make_package "$parent")
printf 'not-a-full-commit\n' > "$package/.ssrplus-upstream-commit"
assert_rejection_preserves_source "$package" 'malformed source provenance marker'

if fix_ssrplus_compat "$test_root/no-such-package" > "$test_root/missing-package.log" 2>&1; then
    fail "missing package directory was accepted"
fi
[[ -s "$test_root/missing-package.log" ]] || fail "missing package was rejected without a diagnostic"
echo "SSR missing patch and package rejection: PASS"

# A scratch directory nested in another repository must remain its own Git
# root. Otherwise git apply can silently skip every package-relative path.
parent="$test_root/tmpdir-parent"
package=$(make_package "$parent")
mkdir -p "$parent/scratch"
TMPDIR="$parent/scratch" fix_ssrplus_compat "$package" > "$test_root/nested-tmpdir.log"
assert_fully_patched "$parent" "$package"
[[ -z $(find "$parent/scratch" -mindepth 1 -print -quit) ]] || fail 'scratch worktree leaked after application'

# The embedded manifest must be auditable independently of the helper's own
# generator. A changed declared digest is rejected before any firmware build.
cp "$package/$manifest_path" "$test_root/trusted-build.json"
python - "$package/$manifest_path" <<'PY'
from pathlib import Path
import json
import sys
path = Path(sys.argv[1])
document = json.loads(path.read_text(encoding="utf-8"))
document["files"]["/usr/share/shadowsocksr/ssrp-runtime.sh"]["sha256"] = "0" * 64
path.write_text(json.dumps(document) + "\n", encoding="utf-8", newline="\n")
PY
if (assert_manifest "$package") > "$test_root/bad-manifest.log" 2>&1; then
    fail 'embedded manifest with a changed program digest was accepted'
fi
cp "$test_root/trusted-build.json" "$package/$manifest_path"
fix_ssrplus_compat "$package" > "$test_root/manifest-repeat.log"
cmp "$test_root/trusted-build.json" "$package/$manifest_path" || fail 'manifest changed on repeated generation'
echo 'SSR nested-Git scratch isolation and independently checked manifest integrity: PASS'

# Exercise the real update stage with only unrelated build helpers replaced.
# Sparse source import must precede this fix, and feeds install must follow it.
(
    source "$repo_root/wrt_core/update.sh"
    eval "$(declare -f fix_ssrplus_compat | sed '1s/fix_ssrplus_compat/apply_reviewed_ssrplus_patch/')"
    # declare -f omits the semicolon after the final simple command.
    while IFS= read -r helper; do
        [[ $helper == fix_ssrplus_compat ]] || eval "$helper() { :; }"
    done < <(declare -f stage_pre_install_source_fixes |
        sed -n -E 's/^[[:space:]]+([a-zA-Z_][a-zA-Z_0-9]*)([[:space:];].*)?$/\1/p')
    feed_parent="$test_root/build-stage"
    get_custom_feed_worktree_dir() { printf '%s\n' "$feed_parent/sparse-feed"; }
    install_custom_feed() {
        make_package "$feed_parent" >/dev/null
        printf 'import\n' >"$test_root/stage-order"
    }
    fix_ssrplus_compat() {
        [[ -s "$test_root/stage-order" ]] || fail 'SSR patch ran before source import'
        [[ $1 == "$feed_parent/sparse-feed/luci-app-ssr-plus" ]] || fail 'SSR patch targets the wrong source directory'
        apply_reviewed_ssrplus_patch "$1" || return 1
        printf 'patch\n' >>"$test_root/stage-order"
    }
    install_feeds() {
        assert_fully_patched "$feed_parent" "$feed_parent/sparse-feed/luci-app-ssr-plus"
        printf 'install\n' >>"$test_root/stage-order"
    }
    stage_custom_feed_prepare
    stage_pre_install_source_fixes
    stage_feeds_install
)
[[ $(cat "$test_root/stage-order") == $'import\npatch\ninstall' ]] ||
    fail 'SSR fix did not run between source import and feeds installation'

# A caller using if/OR suppresses Bash errexit. The production stage must
# explicitly propagate rejection and avoid running every subsequent helper.
status=0
(
    source "$repo_root/wrt_core/update.sh"
    while IFS= read -r helper; do
        [[ $helper == fix_ssrplus_compat ]] ||
            eval "$helper() { [[ ! -e \"\$test_root/stage-rejected\" ]] || fail 'stage continued after SSR rejection'; }"
    done < <(declare -f stage_pre_install_source_fixes |
        sed -n -E 's/^[[:space:]]+([a-zA-Z_][a-zA-Z_0-9]*)([[:space:];].*)?$/\1/p')
    get_custom_feed_worktree_dir() { printf '%s\n' "$test_root/rejected-feed"; }
    fix_ssrplus_compat() { : >"$test_root/stage-rejected"; return 1; }
    stage_pre_install_source_fixes
) || status=$?
[[ $status -eq 1 && -e "$test_root/stage-rejected" ]] ||
    fail "source-fix stage swallowed SSR rejection (status $status)"

echo 'SSR build-stage order and failure propagation: PASS'
