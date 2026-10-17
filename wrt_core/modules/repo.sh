#!/usr/bin/env bash
# 上游源码拉取、清理和复位。

clone_repo() {
    if [[ ! -d $BUILD_DIR ]]; then
        echo "克隆仓库: $REPO_URL 分支: $REPO_BRANCH"
        if ! git_retry clone --depth 1 -b "$REPO_BRANCH" "$REPO_URL" "$BUILD_DIR"; then
            echo "错误：克隆仓库 $REPO_URL 失败" >&2
            exit 1
        fi
    fi
}


checkout_repo_ref() {
    local requested_commit=${COMMIT_HASH:-none}
    local resolved_commit

    if [[ ! -d "$BUILD_DIR/.git" ]]; then
        echo "Build directory is not a Git checkout: $BUILD_DIR" >&2
        return 1
    fi

    if [[ "$requested_commit" == "none" ]]; then
        if ! git_retry -C "$BUILD_DIR" fetch --depth 1 origin "+$REPO_BRANCH:refs/remotes/origin/$REPO_BRANCH"; then
            return 1
        fi
        if ! git_retry -C "$BUILD_DIR" checkout -B "$REPO_BRANCH" "origin/$REPO_BRANCH"; then
            return 1
        fi
        git_retry -C "$BUILD_DIR" reset --hard "origin/$REPO_BRANCH"
        return
    fi

    if [[ ! "$requested_commit" =~ ^[0-9a-fA-F]{40}$ ]]; then
        echo "Invalid COMMIT_HASH (expected a 40-character hexadecimal SHA): $requested_commit" >&2
        return 1
    fi

    if ! git -C "$BUILD_DIR" cat-file -e "$requested_commit^{commit}" 2>/dev/null; then
        if ! git_retry -C "$BUILD_DIR" fetch --depth 1 origin "$requested_commit"; then
            return 1
        fi
    fi

    if ! git -C "$BUILD_DIR" cat-file -e "$requested_commit^{commit}" 2>/dev/null; then
        echo "Pinned commit is unavailable from origin: $requested_commit" >&2
        return 1
    fi

    if ! git_retry -C "$BUILD_DIR" checkout --detach "$requested_commit"; then
        return 1
    fi

    resolved_commit=$(git -C "$BUILD_DIR" rev-parse HEAD) || return 1
    if [[ "$resolved_commit" != "${requested_commit,,}" ]]; then
        echo "Pinned checkout resolved to $resolved_commit instead of $requested_commit" >&2
        return 1
    fi
}


clean_up() {
    if [[ ! -d "$BUILD_DIR" ]]; then
        echo "Build directory $BUILD_DIR does not exist"
        return
    fi
    cd "$BUILD_DIR"
    if [[ -f ".config" ]]; then
        \rm -f ".config"
    fi
    if [[ -d "tmp" ]]; then
        \rm -rf "tmp"
    fi
    if [[ -d "logs" ]]; then
        find "$BUILD_DIR/logs" -type f -delete
    fi
    if [[ -d "feeds" ]]; then
        ./scripts/feeds clean
    fi
    mkdir -p "tmp"
    echo "1" >"tmp/.build"
}


reset_feeds_conf() {
    # 所有源码修正都基于远端分支或指定提交的干净状态。
    git_retry -C "$BUILD_DIR" reset --hard
    git_retry -C "$BUILD_DIR" clean -f -d
    checkout_repo_ref
}
