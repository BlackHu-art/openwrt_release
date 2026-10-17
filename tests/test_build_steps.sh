#!/usr/bin/env bash
set -euo pipefail
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
source "$repo_root/wrt_core/modules/build_steps.sh"
test_root=$(mktemp -d "${TMPDIR:-/tmp}/build-steps.XXXXXX")
trap 'rm -rf -- "$test_root"' EXIT
cd "$test_root"
nproc() { echo 4; }
make() {
    echo "$*" >> calls
    echo "output from $1"
    if [[ "$1" == "${fail_target:-}" ]]; then
        echo 'Hunk FAILED: regression fixture' >&2
        return 23
    fi
}
reset_case() {
    : > calls
    mkdir -p logs
    : > logs/build-times.tsv
    printf '%s\n' "$1" > .config
    fail_target=''
}

reset_case 'CONFIG_PACKAGE_miniupnpd-nftables=y'
build_firmware
[[ $(wc -l < calls) == 3 ]]
sed -n '2p' calls | grep -q '^package/feeds/packages/miniupnpd/prepare -j1 V=s BUILD_LOG=1$'
tail -n1 calls | grep -q '^-j5 V=s BUILD_LOG=1$'
[[ $(wc -l < logs/build-times.tsv) == 3 ]]

reset_case 'CONFIG_PACKAGE_miniupnpd-nftables=y'
fail_target=package/feeds/packages/miniupnpd/prepare
status=0
build_firmware || status=$?
[[ "$status" == 23 && $(wc -l < calls) == 2 ]]
grep -q 'Hunk FAILED' logs/miniupnpd-prepare.log
tail -n1 logs/build-times.tsv | grep -q $'\t23$'

reset_case '# CONFIG_PACKAGE_miniupnpd-nftables is not set'
fail_target=-j5
status=0
build_firmware || status=$?
[[ "$status" == 23 && $(wc -l < calls) == 2 ]]
grep -q 'Hunk FAILED' logs/compile.log
! grep -q -- '-j1' calls

reset_case 'CONFIG_PACKAGE_miniupnpd-iptables=m'
fail_target=download
status=0
build_firmware || status=$?
[[ "$status" == 23 && $(wc -l < calls) == 1 ]]
echo 'build failure propagation and logging: PASS'
