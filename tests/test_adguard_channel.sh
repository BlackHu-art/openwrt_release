#!/usr/bin/env bash
set -euo pipefail
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
BASE_PATH="$repo_root/wrt_core"
source "$BASE_PATH/modules/plugin_compat.sh"
fixtures="$repo_root/tests/fixtures/plugin-runtime"
temp_base=$(cd "${TMPDIR:-/tmp}" && pwd -P)
test_root=$(mktemp -d "$temp_base/adguard-channel.XXXXXX")
cleanup() {
    case "$test_root" in
        "$temp_base"/adguard-channel.*) rm -rf -- "$test_root" ;;
        *) echo "Unexpected test path: $test_root" >&2 ;;
    esac
}
trap cleanup EXIT
fail() { echo "FAIL: $*" >&2; exit 1; }
package="$test_root/package"
mkdir -p "$package/root/usr/share/AdGuardHome" "$package/luasrc/controller"
cp "$fixtures/adguard-updater.sh" "$package/root/usr/share/AdGuardHome/update_core.sh"
cp "$fixtures/adguard-links.txt" "$package/root/usr/share/AdGuardHome/links.txt"
cp "$fixtures/AdGuardHome.lua" "$package/luasrc/controller/AdGuardHome.lua"
git init -q "$package"
git -C "$package" config core.autocrlf false
fix_adguardhome_compat "$package"
updater="$package/root/usr/share/AdGuardHome/update_core.sh"
bash -n "$updater"
cp "$updater" "$test_root/patched-updater"
cp "$package/root/usr/share/AdGuardHome/links.txt" "$test_root/patched-links"
fix_adguardhome_compat "$package"
cmp "$updater" "$test_root/patched-updater" || fail 'repeated helper changed updater'
cmp "$package/root/usr/share/AdGuardHome/links.txt" "$test_root/patched-links" ||
    fail 'repeated helper changed default links'

# Relocate each production absolute path once. The inserted shell variables are
# expanded only when the updater runs, so a Linux /tmp test root cannot be
# replaced again. All updater logic, including main and the download loop, runs.
sed -e 's|^PATH=.*|PATH="$ADG_TEST_BIN:$PATH"|' \
    -e 's|/tmp|${ADG_TEST_ROOT}/tmp|g' \
    -e 's|/var/run|${ADG_TEST_ROOT}/var/run|g' \
    -e 's|/usr/share/AdGuardHome|${ADG_TEST_ROOT}/usr/share/AdGuardHome|g' \
    -e 's|/etc/init.d/AdGuardHome|${ADG_TEST_ROOT}/service|g' \
    "$updater" > "$test_root/updater.sh"

fake_bin="$test_root/bin"
mkdir -p "$fake_bin"
cat > "$fake_bin/uci" <<'EOF'
#!/usr/bin/env bash
case "$*" in
    'get AdGuardHome.AdGuardHome.binpath') printf '%s/core\n' "$ADG_TEST_ROOT" ;;
    'get AdGuardHome.AdGuardHome.upxflag') : ;;
    *) exit 90 ;;
esac
EOF
cat > "$fake_bin/opkg" <<'EOF'
#!/usr/bin/env bash
[[ $* == 'info kernel' ]] || exit 91
printf 'Architecture: x86_64\n'
EOF
cat > "$fake_bin/ps" <<'EOF'
#!/usr/bin/env bash
# No concurrent updater in this isolated runtime.
exit 0
EOF
cat > "$fake_bin/curl" <<'EOF'
#!/usr/bin/env bash
while [[ $# -gt 0 ]]; do
    case "$1" in
        -o) output=$2; shift 2 ;;
        --retry|--connect-timeout) shift 2 ;;
        -L|-k) shift ;;
        *) url=$1; shift ;;
    esac
done
printf '%s\n' "$url" >> "$ADG_TEST_ROOT/downloads"
if [[ $url == https://api.github.com/repos/AdguardTeam/AdGuardHome/releases/latest ]]; then
    [[ $output == - ]] || exit 92
    cat "$ADG_TEST_ROOT/metadata"
    exit
fi
while IFS=$'\t' read -r expected payload; do
    if [[ $url == "$expected" ]]; then
        [[ $output == "$ADG_TEST_ROOT"/tmp/AdGuardHomeupdate/* ]] || exit 93
        printf '%s\n' "$payload" > "$output"
        exit 0
    fi
done < "$ADG_TEST_ROOT/responses"
exit 22
EOF
cat > "$fake_bin/tar" <<'EOF'
#!/usr/bin/env bash
[[ $# == 4 && $1 == -zxf && $3 == -C ]] || exit 94
[[ $2 == "$ADG_TEST_ROOT"/tmp/AdGuardHomeupdate/* &&
   $4 == "$ADG_TEST_ROOT"/tmp/AdGuardHomeupdate/ ]] || exit 95
payload=$(cat "$2")
[[ $payload != corrupt-archive ]] || exit 2
mkdir -p "$4/AdGuardHome"
if [[ $payload == unreadable ]]; then
    printf '#!/usr/bin/env bash\nexit 126\n' > "$4/AdGuardHome/AdGuardHome"
elif [[ $payload == version-error ]]; then
    printf '#!/usr/bin/env bash\nprintf "AdGuard Home, version v1.0.0\\n"\nexit 1\n' > "$4/AdGuardHome/AdGuardHome"
else
    printf '#!/usr/bin/env bash\n[[ $1 == --version ]] || exit 96\nprintf "AdGuard Home, version %%s\\n" "%s"\n' \
        "$payload" > "$4/AdGuardHome/AdGuardHome"
fi
EOF
chmod +x "$fake_bin"/*

github='https://github.com/AdguardTeam/AdGuardHome/releases/download/v1.0.0/AdGuardHome_linux_amd64.tar.gz'
mirror='https://static.adguard.com/adguardhome/release/AdGuardHome_linux_amd64.tar.gz'
beta='https://static.adguard.com/adguardhome/beta/AdGuardHome_linux_amd64.tar.gz'
edge='https://static.adguard.com/adguardhome/edge/AdGuardHome_linux_amd64.tar.gz'
setup_case() {
    case_root="$test_root/cases/$1"
    mkdir -p "$case_root/tmp/run" "$case_root/var/run" "$case_root/usr/share/AdGuardHome"
    cp "$package/root/usr/share/AdGuardHome/links.txt" "$case_root/usr/share/AdGuardHome/links.txt"
    printf '{"tag_name":"v1.0.0","prerelease":false}\n' > "$case_root/metadata"
    : > "$case_root/responses"
    printf '#!/usr/bin/env bash\n[[ $1 == --version ]] || exit 97\nprintf "AdGuard Home, version %%s\\n" "%s"\n' \
        "${2:-v0.9.0}" > "$case_root/core"
    chmod +x "$case_root/core"
    cp "$case_root/core" "$case_root/old-core"
    cat > "$case_root/service" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$ADG_TEST_ROOT/service-calls"
EOF
    chmod +x "$case_root/service"
}
response() { printf '%s\t%s\n' "$1" "$2" >> "$case_root/responses"; }
run_updater() {
    local expected=$1 rc=0
    shift
    env ADG_TEST_ROOT="$case_root" ADG_TEST_BIN="$fake_bin" \
        bash "$test_root/updater.sh" "$@" > "$case_root/log" 2>&1 || rc=$?
    [[ $rc == "$expected" ]] || { cat "$case_root/log"; fail "expected exit $expected, got $rc"; }
}
preserved_core() {
    cmp "$case_root/core" "$case_root/old-core" || fail 'rejected update changed installed core'
    [[ ! -e "$case_root/service-calls" ]] || fail 'rejected update stopped the service'
}
installed_stable() {
    [[ $("$case_root/core" --version) == 'AdGuard Home, version v1.0.0' ]] ||
        fail 'installed binary is not the selected stable version'
    printf 'stop nobackup\nstart\n' > "$case_root/expected-service"
    cmp "$case_root/expected-service" "$case_root/service-calls" || fail 'unexpected service lifecycle'
    grep -Fq 'Local version: v1.0.0, cloud version: v1.0.0.' "$case_root/log" ||
        fail 'success log does not report the actual installed version'
}

test_default_channel() {
    setup_case default
    response "$beta" v1.1.0-b.1
    response "$github" v1.0.0
    response "$mirror" v1.0.0
    run_updater 0
    installed_stable
    sed '1d' "$case_root/downloads" > "$case_root/core-downloads"
    printf '%s\n' "$github" > "$case_root/expected-downloads"
    cmp "$case_root/expected-downloads" "$case_root/core-downloads" || fail 'default did not use pinned stable GitHub asset first'
}
test_first_install() {
    setup_case first-install
    rm "$case_root/core"
    response "$github" v1.0.0
    run_updater 0
    installed_stable
}
test_legacy_links() {
    setup_case legacy
    # User-maintained content survives, including edge and a private mirror.
    printf '%s\n' "$edge" > "$case_root/usr/share/AdGuardHome/links.txt"
    cat "$fixtures/adguard-links.txt" >> "$case_root/usr/share/AdGuardHome/links.txt"
    printf '%s\n' 'https://mirror.example/AdGuardHome_linux_${Arch}.tar.gz' >> "$case_root/usr/share/AdGuardHome/links.txt"
    cp "$case_root/usr/share/AdGuardHome/links.txt" "$case_root/old-links"
    response "$beta" v1.1.0-b.1
    response "$edge" v1.1.0-SNAPSHOT
    response "$mirror" v1.0.0
    run_updater 0
    installed_stable
    cmp "$case_root/old-links" "$case_root/usr/share/AdGuardHome/links.txt" || fail 'updater rewrote user links'
    ! grep -Fxq "$beta" "$case_root/downloads" || fail 'legacy beta URL was downloaded'
    ! grep -Fxq "$edge" "$case_root/downloads" || fail 'legacy edge URL was downloaded'
}
test_candidate_fallback() {
    local payload=$1
    setup_case "fallback-$payload"
    response "$github" "$payload"
    response "$mirror" v1.0.0
    run_updater 0
    installed_stable
    grep -Fxq "$mirror" "$case_root/downloads" || fail 'rejected candidate did not fall back to stable mirror'
}
test_all_invalid() {
    setup_case all-invalid
    response "$github" v1.0.0-b.1
    response "$mirror" unreadable
    run_updater 1
    preserved_core
    ! grep -Fq 'Succeeded in updating core.' "$case_root/log" || fail 'failed validation claimed success'
}
test_custom_wrong_version() {
    setup_case custom-wrong
    printf '%s\n' 'https://mirror.example/AdGuardHome_linux_${Arch}.tar.gz' > "$case_root/usr/share/AdGuardHome/links.txt"
    response 'https://mirror.example/AdGuardHome_linux_amd64.tar.gz' v1.0.1
    run_updater 1
    preserved_core
}
test_version_ordering() {
    local current=$1 mode=$2 expected=$3
    setup_case "order-${current}-${mode:-automatic}" "$current"
    response "$github" v1.0.0
    response "$mirror" v1.0.0
    run_updater 0 "$mode"
    if [[ $expected == update ]]; then installed_stable; else preserved_core; fi
}
test_invalid_metadata() {
    local tag=$1
    setup_case "metadata-${tag:-empty}"
    printf '{"tag_name":"%s","prerelease":false}\n' "$tag" > "$case_root/metadata"
    response "$github" v1.0.0
    run_updater 1
    preserved_core
    [[ $(wc -l < "$case_root/downloads") == 1 ]] || fail 'invalid stable metadata started a core download'
}

failures=0
check() {
    local name=$1
    shift
    if ( "$@" ); then echo "PASS: $name"; else failures=$((failures + 1)); fi
}
check 'stable defaults select the pinned GitHub tag first' test_default_channel
check 'first run installs the selected stable core' test_first_install
check 'preserved beta-first links cannot install beta/edge' test_legacy_links
check 'wrong-version candidate falls back' test_candidate_fallback v1.0.1
check 'prerelease candidate falls back' test_candidate_fallback v1.0.0-b.1
check 'unreadable candidate falls back' test_candidate_fallback unreadable
check 'failed version command falls back' test_candidate_fallback version-error
check 'corrupt archive falls back' test_candidate_fallback corrupt-archive
check 'all invalid candidates preserve running core' test_all_invalid
check 'custom mirror must serve exact stable version' test_custom_wrong_version
check 'matching prerelease upgrades to stable' test_version_ordering v1.0.0-b.1 '' update
check 'higher prerelease does not downgrade automatically' test_version_ordering v1.1.0-b.1 '' preserve
check 'higher prerelease with build metadata does not downgrade' test_version_ordering v1.1.0-b.1+build '' preserve
check 'higher stable does not downgrade automatically' test_version_ordering v1.0.1 '' preserve
check 'equal stable is unchanged' test_version_ordering v1.0.0 '' preserve
check 'force retains explicit downgrade override' test_version_ordering v1.1.0-b.1 force update
check 'prerelease metadata is rejected' test_invalid_metadata v1.0.0-b.1
check 'malformed metadata is rejected' test_invalid_metadata v1.0
check 'missing metadata is rejected' test_invalid_metadata ''
[[ $failures == 0 ]] || fail "$failures AdGuard channel cases failed"
echo 'AdGuard Home stable download channel: PASS'
