#!/usr/bin/env bash

get_feeds_path() {
    local feeds_path="$BUILD_DIR/$FEEDS_CONF"
    if [[ -f "$BUILD_DIR/feeds.conf" ]]; then
        feeds_path="$BUILD_DIR/feeds.conf"
    fi
    printf '%s\n' "$feeds_path"
}

update_feeds() {
    # Validate the complete source set before changing feeds.conf or building an index.
    python3 "$BASE_PATH/feeds_lock.py" prepare "$BUILD_DIR" || return 1

    if [ ! -f "$BUILD_DIR/include/bpf.mk" ]; then
        touch "$BUILD_DIR/include/bpf.mk"
    fi

    # Fetch only immutable commits in temporary trees. Native URL-pinned retries
    # can otherwise leave a default HEAD and index it before verification.
    network_retry python3 "$BASE_PATH/feeds_lock.py" fetch "$BUILD_DIR" || return 1
    python3 "$BASE_PATH/feeds_lock.py" verify "$BUILD_DIR" || return 1
    run_feed_index upstream || return 1
    python3 "$BASE_PATH/feeds_lock.py" verify "$BUILD_DIR" || return 1
}

run_feed_index() {
    local phase="$1" log_file
    shift
    local -a statuses options=()
    mkdir -p "$BUILD_DIR/logs" || return 1
    log_file="$BUILD_DIR/logs/feeds-index-$phase.log"
    if TOPDIR="$BUILD_DIR" ./scripts/feeds update -i "$@" 2>&1 | tee "$log_file"; then
        statuses=("${PIPESTATUS[@]}")
    else
        statuses=("${PIPESTATUS[@]}")
    fi
    [[ ${statuses[0]} -eq 0 && ${statuses[1]} -eq 0 ]] || return 1
    if [[ "$phase" == custom ]]; then
        options=(--only custom_feed)
    elif [[ "$phase" == final ]]; then
        options=(--custom)
    fi
    python3 "$BASE_PATH/feeds_lock.py" check-index "$BUILD_DIR" --log "$log_file" "${options[@]}"
}

install_feeds() {
    # Compatibility patches may change files, but source commits must remain locked.
    python3 "$BASE_PATH/feeds_lock.py" verify "$BUILD_DIR" --custom || return 1
    run_feed_index final || return 1
    python3 "$BASE_PATH/feeds_lock.py" verify "$BUILD_DIR" --custom || return 1
    TOPDIR="$BUILD_DIR" ./scripts/feeds install -a -f
}
