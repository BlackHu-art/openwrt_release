#!/usr/bin/env bash
set -euo pipefail
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
source "$repo_root/wrt_core/modules/build_steps.sh"
temp_base=$(cd "${TMPDIR:-/tmp}" && pwd -P)
test_root=$(mktemp -d "$temp_base/build-steps.XXXXXX")
cleanup() {
    case "$test_root" in
        "$temp_base"/build-steps.*) rm -rf -- "$test_root" ;;
        *) echo "Refusing to remove unexpected test directory: $test_root" >&2 ;;
    esac
}
trap cleanup EXIT
cd "$test_root"
nproc() { echo 4; }
make() {
    echo "$*" >> calls
    printf "make[3]: Entering directory '%s/feeds/packages/net/example'\n" "$(pwd -P)"
    # Recursive make must not repeat the same package progress or expose internals.
    printf "make[4]: Entering directory '%s/feeds/packages/net/example'\n" "$(pwd -P)"
    printf "make[4]: Entering directory '%s/build_dir/target/example'\n" "$(pwd -P)"
    echo "ccache gcc -DVERBOSE_SENTINEL -c source.c (target $1)"
    if [[ "$1" == "${fail_target:-}" ]]; then
        # Failed mirrors may recover before a later, unrelated build failure.
        for ((line=0; line<recovered_download_errors; line++)); do
            echo 'curl: (22) The requested URL returned error: 403' >&2
        done
        echo 'error-context-before'
        echo "$error_message" >&2
        echo 'error-context-after'
        # Parallel jobs can keep producing output long after the real failure.
        for ((line=0; line<300; line++)); do echo "remaining parallel output $line"; done
        return 23
    fi
    echo 'time: package/feeds/packages/example/compile#0.10#0.20#0.30'
}
reset_case() {
    : > calls
    mkdir -p logs
    : > logs/build-times.tsv
    printf '%s\n' "$1" > .config
    fail_target=''
    error_message='Hunk #1 FAILED at 42.'
    recovered_download_errors=0
}

reset_case 'CONFIG_PACKAGE_miniupnpd-nftables=y'
build_firmware > console.log 2>&1
[[ $(wc -l < calls) == 3 ]]
sed -n '2p' calls | grep -q '^package/feeds/packages/miniupnpd/prepare -j1 V=s BUILD_LOG=1$'
tail -n1 calls | grep -q '^-j5 V=s BUILD_LOG=1$'
[[ $(wc -l < logs/build-times.tsv) == 3 ]]
if grep -qE 'VERBOSE_SENTINEL|build_dir/target/example|Failure details' console.log; then
    echo 'FAIL: successful build leaked detailed output to the console' >&2
    exit 1
fi
grep -q 'feeds/packages/net/example' console.log
grep -q '^time: package/feeds/packages/example/compile' console.log
[[ $(grep -c 'feeds/packages/net/example' console.log) == 3 ]]
for step in download miniupnpd-prepare compile; do
    grep -q VERBOSE_SENTINEL "logs/$step.log"
done

reset_case 'CONFIG_PACKAGE_miniupnpd-nftables=y'
fail_target=package/feeds/packages/miniupnpd/prepare
status=0
build_firmware > console.log 2>&1 || status=$?
[[ "$status" == 23 && $(wc -l < calls) == 2 ]]
grep -q 'Hunk #1 FAILED' logs/miniupnpd-prepare.log
grep -q 'Hunk #1 FAILED' console.log
grep -q 'error-context-before' console.log
grep -q 'error-context-after' console.log
grep -q 'Failure details' console.log
tail -n1 logs/build-times.tsv | grep -q $'\t23$'

reset_case '# CONFIG_PACKAGE_miniupnpd-nftables is not set'
fail_target=-j5
recovered_download_errors=20
error_message=' * check_data_file_clashes: Package luci-app-argon-config wants to install a file already owned by luci-theme-argon'
status=0
GITHUB_ACTIONS=true build_firmware > console.log 2>&1 || status=$?
[[ "$status" == 23 && $(wc -l < calls) == 2 ]]
grep -q 'check_data_file_clashes' logs/compile.log
if ! grep -q 'check_data_file_clashes' console.log; then
    echo 'FAIL: recovered mirror errors hid the actual installation failure' >&2
    exit 1
fi
grep -q '^::group::' console.log
grep -q '^::endgroup::$' console.log
if grep -q -- '-j1' calls; then
    echo 'FAIL: compilation failure triggered a single-threaded retry' >&2
    exit 1
fi

reset_case 'CONFIG_PACKAGE_miniupnpd-iptables=m'
fail_target=download
error_message='curl: (22) The requested URL returned error: 404'
status=0
build_firmware > console.log 2>&1 || status=$?
[[ "$status" == 23 && $(wc -l < calls) == 1 ]]
grep -q 'curl: (22)' console.log

# Unclassified errors still get the raw tail; reporting must not hide failures.
status=0
run_build_step unknown bash -c 'echo unusual-failure >&2; exit 41' > console.log 2>&1 || status=$?
[[ "$status" == 41 ]]
grep -q unusual-failure console.log

# Both the log writer and the progress filter belong to the pipeline contract.
(
    tee() { command tee "$@"; return 17; }
    status=0
    run_build_step log-write printf 'ok\n' > console.log 2>&1 || status=$?
    [[ "$status" == 17 ]]
    tail -n1 logs/build-times.tsv | grep -q $'\t17$'
)
(
    summarize_build_output() { cat >/dev/null; return 19; }
    status=0
    run_build_step filter printf 'ok\n' > console.log 2>&1 || status=$?
    [[ "$status" == 19 ]]
    tail -n1 logs/build-times.tsv | grep -q $'\t19$'
    tee() { command tee "$@"; return 17; }
    status=0
    run_build_step original-error bash -c 'echo original-error; exit 23' > console.log 2>&1 || status=$?
    [[ "$status" == 23 ]]
)

# A broken log directory must stop the command before running it without a log.
(
    mkdir unwritable
    cd unwritable
    : > logs
    status=0
    run_build_step blocked bash -c 'touch should-not-run' > console.log 2>&1 || status=$?
    [[ "$status" != 0 && ! -e should-not-run ]]
)
echo 'build failure propagation and logging: PASS'
