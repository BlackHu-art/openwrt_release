#!/usr/bin/env bash
# Keep the first failure and its verbose log; do not repeat world with -j1.

run_build_step() {
    local name=$1 started=$SECONDS status=0
    local -a statuses
    shift
    mkdir -p logs
    echo "Build step: $name"
    if "$@" 2>&1 | tee "logs/$name.log"; then
        statuses=("${PIPESTATUS[@]}")
    else
        statuses=("${PIPESTATUS[@]}")
    fi
    status=${statuses[0]}
    [[ "$status" != 0 ]] || status=${statuses[1]}
    printf '%s\t%s\t%s\n' "$name" "$((SECONDS - started))" "$status" >> logs/build-times.tsv
    if [[ "$status" != 0 ]]; then
        echo "Build step $name failed (exit $status). See logs/$name.log; automatic world retry is disabled." >&2
    fi
    return "$status"
}

build_firmware() {
    local jobs=$(($(nproc) + 1))
    run_build_step download make download "-j$(($(nproc) * 2))" V=s BUILD_LOG=1 || return $?
    # Reject patch drift before starting all the expensive firmware packages.
    if grep -qE '^CONFIG_PACKAGE_miniupnpd(-(nftables|iptables))?=[ym]$' .config; then
        run_build_step miniupnpd-prepare make package/feeds/packages/miniupnpd/prepare -j1 V=s BUILD_LOG=1 || return $?
    fi
    run_build_step compile make "-j$jobs" V=s BUILD_LOG=1
}
