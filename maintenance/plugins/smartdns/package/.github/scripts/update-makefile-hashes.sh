#!/bin/bash
#
# Calculate new hashes and update Makefile
# Usage: update-makefile-hashes.sh <download_dir>
#

set -euo pipefail

DL_DIR="${1:-dl}"
MAKEFILE="${2:-Makefile}"

# Required environment variables
: "${PKG_NAME:?PKG_NAME is required}"
: "${PKG_VERSION:?PKG_VERSION is required}"
: "${PKG_MIRROR_HASH_OLD:?PKG_MIRROR_HASH_OLD is required}"
: "${SMARTDNS_WEBUI_VERSION:?SMARTDNS_WEBUI_VERSION is required}"
: "${SMARTDNS_WEBUI_HASH_OLD:?SMARTDNS_WEBUI_HASH_OLD is required}"

SMARTDNS_TARBALL="${DL_DIR}/${PKG_NAME}-${PKG_VERSION}.tar.zst"
WEBUI_TARBALL="${DL_DIR}/smartdns-webui-${SMARTDNS_WEBUI_VERSION}.tar.gz"

# Verify files exist
if [[ ! -f "$SMARTDNS_TARBALL" ]]; then
    echo "ERROR: SmartDNS tarball not found: $SMARTDNS_TARBALL" >&2
    exit 1
fi

if [[ ! -f "$WEBUI_TARBALL" ]]; then
    echo "ERROR: WebUI tarball not found: $WEBUI_TARBALL" >&2
    exit 1
fi

echo "==> Calculating new hashes..."

NEW_SMARTDNS_HASH=$(sha256sum "$SMARTDNS_TARBALL" | awk '{print $1}')
NEW_WEBUI_HASH=$(sha256sum "$WEBUI_TARBALL" | awk '{print $1}')

echo "    SmartDNS: ${PKG_MIRROR_HASH_OLD} -> ${NEW_SMARTDNS_HASH}"
echo "    WebUI:    ${SMARTDNS_WEBUI_HASH_OLD} -> ${NEW_WEBUI_HASH}"

echo "==> Updating Makefile..."

# Update hashes in Makefile
sed -i "s/${PKG_MIRROR_HASH_OLD}/${NEW_SMARTDNS_HASH}/" "$MAKEFILE"
sed -i "s/${SMARTDNS_WEBUI_HASH_OLD}/${NEW_WEBUI_HASH}/" "$MAKEFILE"

echo "==> Done updating hashes in ${MAKEFILE}"

# Output new hashes for downstream use
echo "NEW_SMARTDNS_HASH=${NEW_SMARTDNS_HASH}"
echo "NEW_WEBUI_HASH=${NEW_WEBUI_HASH}"
