#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
test_root=$(mktemp -d)
trap 'rm -rf "$test_root"' EXIT
NETWORK_RETRY_MAX=1

remote="$test_root/upstream.git"
writer="$test_root/writer"
checkout="$test_root/checkout"

git init --bare "$remote" >/dev/null
git init -b main "$writer" >/dev/null
git -C "$writer" config user.name 'Repo checkout test'
git -C "$writer" config user.email 'repo-checkout@example.invalid'
git -C "$writer" remote add origin "file://$remote"

commit_file() {
    local contents=$1
    printf '%s\n' "$contents" >"$writer/revision"
    git -C "$writer" add revision
    git -C "$writer" commit -m "$contents" >/dev/null
    git -C "$writer" push origin main >/dev/null
    git -C "$writer" rev-parse HEAD
}

commit_a=$(commit_file A)
commit_b=$(commit_file B)
git clone --depth 1 -b main "file://$remote" "$checkout" >/dev/null

source "$repo_root/wrt_core/modules/network.sh"
source "$repo_root/wrt_core/modules/repo.sh"

BUILD_DIR="$checkout"
REPO_URL="file://$remote"
REPO_BRANCH=main

# A shallow clone at B must explicitly fetch a pinned ancestor A.
COMMIT_HASH="$commit_a"
checkout_repo_ref
test "$(git -C "$checkout" rev-parse HEAD)" = "$commit_a"
test "$(git -C "$checkout" rev-parse --abbrev-ref HEAD)" = HEAD

# A detached pinned checkout must remain pinned after the remote advances to C.
commit_c=$(commit_file C)
COMMIT_HASH="$commit_a"
checkout_repo_ref
test "$(git -C "$checkout" rev-parse HEAD)" = "$commit_a"
test "$(git -C "$checkout" rev-parse --abbrev-ref HEAD)" = HEAD

# An unpinned checkout must return to the current remote branch head.
COMMIT_HASH=none
checkout_repo_ref
test "$(git -C "$checkout" rev-parse HEAD)" = "$commit_c"
test "$(git -C "$checkout" rev-parse --abbrev-ref HEAD)" = main

# A syntactically valid but unavailable pin must fail without moving HEAD.
head_before_failure=$(git -C "$checkout" rev-parse HEAD)
COMMIT_HASH=0123456789abcdef0123456789abcdef01234567
if checkout_repo_ref; then
    echo 'unavailable pin unexpectedly succeeded' >&2
    exit 1
fi
test "$(git -C "$checkout" rev-parse HEAD)" = "$head_before_failure"

# A malformed pin must be rejected before it can change the current checkout.
COMMIT_HASH=not-a-sha
if checkout_repo_ref; then
    echo 'malformed pin unexpectedly succeeded' >&2
    exit 1
fi
test "$(git -C "$checkout" rev-parse HEAD)" = "$head_before_failure"

# pre_clone must record the resolved pin, including the hash consumed by cache keys.
fixture_root="$test_root/pre-clone-fixture"
mkdir -p "$fixture_root"
cp -R "$repo_root/wrt_core" "$fixture_root/wrt_core"
cat >"$fixture_root/wrt_core/compilecfg/fixture.ini" <<EOF
REPO_URL=file://$remote
REPO_BRANCH=main
COMMIT_HASH=$commit_a
EOF
python3 - "$fixture_root/wrt_core/feeds.lock.json" "$REPO_URL" "$commit_a" <<'PYLOCK'
import json
from pathlib import Path
import sys
path, url, commit = sys.argv[1:]
Path(path).write_text(json.dumps({
    "schema": 1,
    "cores": [{"url": url, "commit": commit, "feed_set": "fixture"}],
    "feed_sets": {"fixture": {"packages": {
        "url": "https://example.invalid/packages.git", "commit": "f" * 40,
    }}},
}) + "\n")
PYLOCK
source_lock_hash=$(sha256sum "$fixture_root/wrt_core/feeds.lock.json" | awk '{print $1}')
github_env="$test_root/github_env"
: >"$github_env"
(
    cd "$fixture_root"
    GITHUB_ENV="$github_env" "$fixture_root/wrt_core/pre_clone_action.sh" fixture
)
test "$(git -C "$fixture_root/action_build" rev-parse HEAD)" = "$commit_a"
expected_repo_flag=$(printf '%s\nfeeds_lock_sha256=%s\n' "file://$remote/main@$commit_a" "$source_lock_hash")
test "$(cat "$fixture_root/repo_flag")" = "$expected_repo_flag"
expected_repo_hash=$(sha256sum "$fixture_root/repo_flag" | awk '{print $1}')
grep -Fx "REPO_HASH=$expected_repo_hash" "$github_env"
grep -Fx "PRECLONE_COMMIT_HASH=$commit_a" "$github_env"
grep -Fx "PRECLONE_FEEDS_LOCK_SHA256=$source_lock_hash" "$github_env"

# A source-lock change with an identical core must invalidate the CI cache key.
python3 - "$fixture_root/wrt_core/feeds.lock.json" <<'PYLOCK'
import json
from pathlib import Path
import sys
path = Path(sys.argv[1])
data = json.loads(path.read_text())
data["review_note"] = "changed reviewed feed lock"
path.write_text(json.dumps(data) + "\n")
PYLOCK
(
    cd "$fixture_root"
    GITHUB_ENV="$github_env" "$fixture_root/wrt_core/pre_clone_action.sh" fixture
)
changed_repo_hash=$(sha256sum "$fixture_root/repo_flag" | awk '{print $1}')
test "$changed_repo_hash" != "$expected_repo_hash"
grep -Fx "REPO_HASH=$changed_repo_hash" "$github_env"

# The workflow must retain the exact source revision selected by pre-clone even
# if the remote branch advances before the build job consumes GITHUB_ENV.
commit_d=$(commit_file D)
test "$(git -C "$fixture_root/action_build" rev-parse HEAD)" = "$commit_a"
grep -Fx "PRECLONE_COMMIT_HASH=$commit_a" "$github_env"

echo 'repo checkout behavior: PASS'
