#!/usr/bin/env bash

# Determine wrt_core path
if [ -d "wrt_core" ]; then
    WRT_CORE_PATH="wrt_core"
elif [ -d "../wrt_core" ]; then
    WRT_CORE_PATH="../wrt_core"
else
    # Fallback to script directory if wrt_core is current dir or relative
    WRT_CORE_PATH=$(dirname "$0")
fi

BASE_PATH=$(cd "$WRT_CORE_PATH" && pwd)

source "$BASE_PATH/modules/network.sh"
source "$BASE_PATH/modules/repo.sh"

Dev=$1

INI_FILE="$BASE_PATH/compilecfg/$Dev.ini"

if [[ ! -f $INI_FILE ]]; then
    echo "INI file not found: $INI_FILE"
    exit 1
fi

read_ini_by_key() {
    local key=$1
    awk -F"=" -v key="$key" '$1 == key {print $2}' "$INI_FILE"
}

REPO_URL=$(read_ini_by_key "REPO_URL")
REPO_BRANCH=$(read_ini_by_key "REPO_BRANCH")
REPO_BRANCH=${REPO_BRANCH:-main}
COMMIT_HASH=$(read_ini_by_key "COMMIT_HASH")
COMMIT_HASH=${COMMIT_HASH:-none}
# GitHub Actions usually runs in root of repo, so build dir should be relative to repo root
# We need to construct absolute path or ensure context is correct.
# Assuming this script is run from repo root or wrt_core.
# Let's use relative path "action_build" next to wrt_core if possible or just use what works.
# Original script used BASE_PATH/action_build.
BUILD_DIR="$BASE_PATH/../action_build"

# Validate the configured immutable source before cloning or reusing a tree.
FEEDS_LOCK_SHA256=$(python3 "$BASE_PATH/feeds_lock.py" identity --repo-url "$REPO_URL" --commit "$COMMIT_HASH") || exit 1

echo "$REPO_URL $REPO_BRANCH"
clone_repo
if ! checkout_repo_ref; then
    exit 1
fi

RESOLVED_SHA=$(git -C "$BUILD_DIR" rev-parse HEAD) || exit 1
ACTUAL_FEEDS_LOCK_SHA256=$(python3 "$BASE_PATH/feeds_lock.py" identity --tree "$BUILD_DIR") || exit 1
if [[ "$ACTUAL_FEEDS_LOCK_SHA256" != "$FEEDS_LOCK_SHA256" ]]; then
    echo "Error: source lock changed during pre-clone." >&2
    exit 1
fi
REPO_FLAG="$BASE_PATH/../repo_flag"
printf '%s\nfeeds_lock_sha256=%s\n' "$REPO_URL/$REPO_BRANCH@$RESOLVED_SHA" "$FEEDS_LOCK_SHA256" >"$REPO_FLAG"
if [[ -n ${GITHUB_ENV:-} ]]; then
    REPO_HASH=$(sha256sum "$REPO_FLAG" | awk '{print $1}')
    echo "REPO_HASH=$REPO_HASH" >>"$GITHUB_ENV"
    echo "PRECLONE_COMMIT_HASH=$RESOLVED_SHA" >>"$GITHUB_ENV"
    echo "PRECLONE_FEEDS_LOCK_SHA256=$FEEDS_LOCK_SHA256" >>"$GITHUB_ENV"
fi

# GitHub Action 移除国内下载源
PROJECT_MIRRORS_FILE="$BUILD_DIR/scripts/projectsmirrors.json"

if [ -f "$PROJECT_MIRRORS_FILE" ]; then
    sed -i '/.cn\//d; /tencent/d; /aliyun/d' "$PROJECT_MIRRORS_FILE"
fi
