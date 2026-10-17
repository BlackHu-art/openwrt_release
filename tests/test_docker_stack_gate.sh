#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
source "$repo_root/wrt_core/modules/docker.sh"

tmp_dir=$(mktemp -d)
trap 'rm -rf "$tmp_dir"' EXIT

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

expect_selected() {
    if ! docker_stack_selected_in_configs "$@"; then
        fail "expected Docker stack to be selected for: $*"
    fi
}

expect_not_selected() {
    local status=0

    if docker_stack_selected_in_configs "$@"; then
        fail "expected Docker stack to be unselected for: $*"
    else
        status=$?
    fi

    [[ $status -eq 1 ]] || fail "expected unselected status 1, got $status"
}

expect_error() {
    local status=0

    if docker_stack_selected_in_configs "$@"; then
        fail "expected Docker stack selection error for: $*"
    else
        status=$?
    fi

    [[ $status -gt 1 ]] || fail "expected selection error status >1, got $status"
}

plain_config="$tmp_dir/plain.config"
docker_deps_copy="$tmp_dir/docker_deps.config"
dockerman_config="$tmp_dir/dockerman.config"
dockerd_config="$tmp_dir/dockerd.config"
dockerd_disabled_config="$tmp_dir/dockerd-disabled.config"
same_file_override_config="$tmp_dir/same-file-override.config"
override_config="$tmp_dir/override.config"

printf '%s\n' 'CONFIG_PACKAGE_nftables=y' > "$plain_config"
cp "$repo_root/wrt_core/deconfig/fragments/docker_deps.config" "$docker_deps_copy"
printf '%s\n' 'CONFIG_PACKAGE_luci-app-dockerman=m' > "$dockerman_config"
printf '%s\n' 'CONFIG_PACKAGE_dockerd=y' > "$dockerd_config"
printf '%s\n' 'CONFIG_PACKAGE_dockerd=n' > "$dockerd_disabled_config"
printf '%s\n' 'CONFIG_PACKAGE_dockerd=y' 'CONFIG_PACKAGE_dockerd=n' > "$same_file_override_config"
printf '%s\n' '# CONFIG_PACKAGE_luci-app-dockerman is not set' > "$override_config"

expect_not_selected "$plain_config"
expect_not_selected "$docker_deps_copy"
expect_selected "$dockerman_config"
expect_not_selected "$dockerman_config" "$override_config"
expect_selected "$dockerd_config"
expect_not_selected "$dockerd_disabled_config"
expect_not_selected "$same_file_override_config"
expect_error "$tmp_dir/missing.config"

fake_awk_dir="$tmp_dir/fake-awk"
mkdir -p "$fake_awk_dir"
printf '%s\n' '#!/usr/bin/env bash' 'exit 73' > "$fake_awk_dir/awk"
chmod +x "$fake_awk_dir/awk"
if PATH="$fake_awk_dir:$PATH" docker_stack_selected_in_configs "$plain_config"; then
    fail "awk failure was accepted as Docker stack selection"
else
    status=$?
fi
[[ $status -gt 1 ]] || fail "awk failure returned $status instead of an error"

sync_calls=0
docker_stack_sync_nftables_compat() {
    sync_calls=$((sync_calls + 1))
}

docker_stack_sync_nftables_compat_if_selected 0 "$tmp_dir/build" 0
[[ $sync_calls -eq 0 ]] || fail "unselected Docker stack invoked sync"

docker_stack_sync_nftables_compat_if_selected 1 "$tmp_dir/build" 0
[[ $sync_calls -eq 1 ]] || fail "selected Docker stack did not invoke sync exactly once"

if docker_stack_sync_nftables_compat_if_selected invalid "$tmp_dir/build" 0; then
    fail "invalid Docker stack selection was accepted"
fi

network_stub_dir="$tmp_dir/network-stubs"
network_marker="$tmp_dir/network-called"
mkdir -p "$network_stub_dir"
for command in git curl wget; do
    printf '%s\n' '#!/usr/bin/env bash' 'printf "%s\\n" "${0##*/}" >> "${NETWORK_MARKER:?}"' 'exit 97' > "$network_stub_dir/$command"
    chmod +x "$network_stub_dir/$command"
done

expect_update_rejected_before_stages() {
    local description=$1
    shift
    local status=0

    rm -f "$network_marker"
    if NETWORK_MARKER="$network_marker" PATH="$network_stub_dir:$PATH" "$repo_root/wrt_core/update.sh" "$@"; then
        fail "$description was accepted"
    else
        status=$?
    fi

    [[ $status -eq 2 ]] || fail "$description returned $status instead of 2"
    [[ ! -e $network_marker ]] || fail "$description entered a repo or network stage"
}

expect_update_rejected_before_stages "missing Docker stack selection" url branch "$tmp_dir/direct-build" commit
expect_update_rejected_before_stages "invalid Docker stack selection" url branch "$tmp_dir/direct-build" commit invalid

# Loading update.sh is a library operation: it must not enable errexit or
# errtrace in a caller that deliberately disabled both options.
if ! (
    set +e +E
    source "$repo_root/wrt_core/update.sh"
    [[ $- != *e* ]]
    ! shopt -qo errtrace
); then
    fail "sourcing update.sh must not change the caller's errexit or errtrace options"
fi

if ! (
    export NETWORK_MARKER="$network_marker"
    export PATH="$network_stub_dir:$PATH"
    rm -f "$network_marker"
    source "$repo_root/wrt_core/update.sh" url branch "$tmp_dir/source-build" commit 0
    declare -F clone_repo >/dev/null || exit 1
    [[ ! -e $network_marker ]] || exit 1

    for helper in \
        verify_custom_feed_installed_paths \
        fix_easytier_lua update_adguardhome update_script_priority update_geoip \
        fix_openssl_ktls fix_opkg_check fix_netfilter_kmod_clash fix_quectel_cm \
        install_pbr_cmcc fix_pbr_ip_forward; do
        eval "$helper() { :; }"
    done

    sync_calls=0
    docker_stack_sync_nftables_compat() {
        sync_calls=$((sync_calls + 1))
    }

    BUILD_DIR="$tmp_dir/source-build"
    DOCKER_STACK_SELECTED=0
    stage_post_install_package_fixes
    [[ $sync_calls -eq 0 ]]

    DOCKER_STACK_SELECTED=1
    stage_post_install_package_fixes
    [[ $sync_calls -eq 1 ]]
); then
    fail "update.sh must be sourceable without running main, and its post-install stage must honor Docker selection"
fi

preview=$(cd "$repo_root" && ./build.sh cmcc_rax3000m_immwrt config_preview)
[[ $preview == *"Docker stack selected: 0"* ]] || fail "cmcc_rax3000m_immwrt should not select Docker"

preclone_sha=0123456789abcdef0123456789abcdef01234567
preview=$(cd "$repo_root" && PRECLONE_COMMIT_HASH="$preclone_sha" ./build.sh cmcc_rax3000m_immwrt config_preview)
[[ $preview == *"Source commit: $preclone_sha"* ]] || fail "config preview must report the frozen pre-clone source commit"

if preview=$(cd "$repo_root" && PRECLONE_COMMIT_HASH=not-a-sha ./build.sh cmcc_rax3000m_immwrt config_preview 2>&1); then
    fail "invalid PRECLONE_COMMIT_HASH was accepted"
fi
[[ $preview == *"PRECLONE_COMMIT_HASH"* ]] || fail "invalid PRECLONE_COMMIT_HASH did not explain the failure"

if preview=$(cd "$repo_root" && PRECLONE_COMMIT_HASH="$preclone_sha" ./build.sh jdcloud_ipq60xx_immwrt config_preview 2>&1); then
    fail "a configured COMMIT_HASH that differs from pre-clone SHA was accepted"
fi
[[ $preview == *"does not match"* ]] || fail "mismatched source pins did not explain the failure"

preview=$(cd "$repo_root" && ADD_CONFIG_FRAGMENTS=docker_deps ./build.sh cmcc_rax3000m_immwrt config_preview)
[[ $preview == *"Docker stack selected: 0"* ]] || fail "docker_deps alone should not select Docker"

preview=$(cd "$repo_root" && ./build.sh x64_immwrt config_preview)
[[ $preview == *"Docker stack selected: 1"* ]] || fail "x64_immwrt should select Docker"

for model in jdcloud_ipq60xx_immwrt jdcloud_ipq60xx_libwrt jdcloud_ax6000_immwrt; do
    preview=$(cd "$repo_root" && ./build.sh "$model" config_preview)
    [[ $preview == *"Docker stack selected: 0"* ]] || fail "$model should not select Docker"
    [[ $preview != *"docker_deps"* ]] || fail "$model should not include Docker dependencies by default"
done

echo "docker stack gate tests passed"
