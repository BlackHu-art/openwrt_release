#!/usr/bin/env bash
# Keep full logs on disk, show progress live, and expand details only on failure.
source "$(dirname "${BASH_SOURCE[0]}")/ssrplus_build.sh"
BUILD_STEPS_CORE_PATH=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

summarize_build_output() {
    awk -v root="${1%/}/" '
        /^g?make(\[[0-9]+\])?: Entering directory / {
            path = $0
            sub(/^[^:]+: Entering directory [\047`]/, "", path)
            sub(/\047$/, "", path)
            if (index(path, root) == 1) {
                path = substr(path, length(root) + 1)
                if (path ~ /^(tools|toolchain|target|package|feeds)\// && !seen[path]++) {
                    print "  -> " path
                    fflush()
                }
            }
            next
        }
        /^time: / || /^[[:space:]]*(ERROR|WARNING):/ {
            print
            fflush()
        }
    '
}

report_build_failure() {
    local name=$1 log_file=$2
    # Include early errors even when other parallel jobs filled the end of the log.
    local error_pattern='(^|[[:space:]])Hash mismatch for file |Hunk #[0-9]+ FAILED|:[0-9]+:[0-9]+: (fatal )?error:|^error(\[[^]]+\])?:|^CMake Error|^FAILED:|^[[:space:]]*\* (check_data_file_clashes|opkg_install_cmd|pkg_hash_check_unresolved|satisfy_dependencies):|No space left on device|Killed signal|^[[:space:]]*ERROR:.*failed to build'
    if [[ ${GITHUB_ACTIONS:-} == true ]]; then
        echo "::group::Failure details: $name"
    else
        echo "Failure details: $name"
    fi
    if [[ -f "$log_file" ]]; then
        # A mirror can fail and recover; prefer actual build errors when present.
        if ! grep -qE -- "$error_pattern" "$log_file"; then
            error_pattern='^curl: \([0-9]+\)'
        fi
        echo 'Error context (first 5 matches):'
        grep -n -E -m 5 -B 5 -A 10 -- "$error_pattern" "$log_file" || true
        echo 'Last 80 log lines:'
        tail -n 80 -- "$log_file" || true
    else
        echo "Detailed log unavailable: $log_file"
    fi
    if [[ ${GITHUB_ACTIONS:-} == true ]]; then
        echo '::endgroup::'
    fi
}

run_build_step() {
    local name=$1 started=$SECONDS status=0
    local -a statuses
    shift
    mkdir -p logs || return $?
    echo "Build step: $name"
    if "$@" 2>&1 | tee "logs/$name.log" | summarize_build_output "$(pwd -P)"; then
        statuses=("${PIPESTATUS[@]}")
    else
        statuses=("${PIPESTATUS[@]}")
    fi
    status=${statuses[0]}
    [[ "$status" != 0 ]] || status=${statuses[1]}
    [[ "$status" != 0 ]] || status=${statuses[2]}
    printf '%s\t%s\t%s\n' "$name" "$((SECONDS - started))" "$status" >> logs/build-times.tsv
    if [[ "$status" != 0 ]]; then
        echo "Build step $name failed (exit $status). See logs/$name.log; automatic world retry is disabled." >&2
        report_build_failure "$name" "logs/$name.log" >&2 || true
    fi
    return "$status"
}

build_firmware() {
    local jobs=$(($(nproc) + 1))
    python "$BUILD_STEPS_CORE_PATH/download_compat.py" . || return $?
    run_build_step download make download "-j$(($(nproc) * 2))" V=s BUILD_LOG=1 || return $?
    # Reject patch drift before starting all the expensive firmware packages.
    if grep -qE '^CONFIG_PACKAGE_miniupnpd(-(nftables|iptables))?=[ym]$' .config; then
        run_build_step miniupnpd-prepare make package/feeds/packages/miniupnpd/prepare -j1 V=s BUILD_LOG=1 || return $?
    fi
    run_build_step compile make "-j$jobs" V=s BUILD_LOG=1 || return $?
    verify_ssrplus_built_artifacts
}
