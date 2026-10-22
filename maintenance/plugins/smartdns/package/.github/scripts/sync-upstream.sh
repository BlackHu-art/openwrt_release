#!/bin/bash
#
# Sync with upstream repository while preserving .github directory
# Usage: sync-upstream.sh [upstream_url] [upstream_branch]
#
# This script:
# 1. Adds upstream remote if not exists
# 2. Fetches upstream changes
# 3. Resets to upstream (preserving .github)
# 4. Checks if Makefile versions changed
#
# Outputs:
#   changed=true/false to GITHUB_OUTPUT
#

set -euo pipefail

UPSTREAM_URL="${1:-https://github.com/pymumu/openwrt-smartdns.git}"
UPSTREAM_BRANCH="${2:-master}"

# Function to extract version variables from Makefile
get_makefile_vars() {
    grep -E "^(PKG_VERSION|PKG_SOURCE_VERSION|SMARTDNS_WEBUI_VERSION|SMARTDNS_WEBUI_SOURCE_VERSION)[[:space:]]*:?=" Makefile | sort
}

echo "==> Capturing current Makefile variables..."
BEFORE_VARS=$(get_makefile_vars)
echo "$BEFORE_VARS"

# Add upstream remote if not exists
if ! git remote get-url upstream &>/dev/null; then
    echo "==> Adding upstream remote: ${UPSTREAM_URL}"
    git remote add upstream "${UPSTREAM_URL}"
fi

echo "==> Fetching upstream..."
git fetch upstream

# Save current HEAD to restore .github later
CURRENT_HEAD=$(git rev-parse HEAD)

echo "==> Resetting to upstream/${UPSTREAM_BRANCH}..."
git reset --hard "upstream/${UPSTREAM_BRANCH}"

# CRITICAL: Restore .github directory from the original commit
# This preserves our custom workflows and scripts
echo "==> Restoring .github directory from ${CURRENT_HEAD}..."
git checkout "${CURRENT_HEAD}" -- .github/

echo "==> Capturing upstream Makefile variables..."
AFTER_VARS=$(get_makefile_vars)
echo "$AFTER_VARS"

# Check for changes and output result
if [[ "$BEFORE_VARS" != "$AFTER_VARS" ]]; then
    echo "changed=true" >> "${GITHUB_OUTPUT:-/dev/stdout}"
    echo "==> Changes detected in Makefile versions."
else
    echo "changed=false" >> "${GITHUB_OUTPUT:-/dev/stdout}"
    echo "==> No changes in Makefile versions."
fi
