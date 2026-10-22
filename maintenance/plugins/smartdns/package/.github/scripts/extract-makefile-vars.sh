#!/bin/bash
#
# Extract variables from Makefile for SmartDNS package
# Outputs key=value pairs suitable for GITHUB_ENV
#

set -euo pipefail

MAKEFILE="${1:-Makefile}"

if [[ ! -f "$MAKEFILE" ]]; then
    echo "ERROR: Makefile not found: $MAKEFILE" >&2
    exit 1
fi

# Function to extract a variable from Makefile
extract_var() {
    local var_name="$1"
    grep -E "^${var_name}[[:space:]]*:?=" "$MAKEFILE" | head -n 1 | sed -E "s/^${var_name}[[:space:]]*:?=(.*)/\1/" | xargs
}

# Extract SmartDNS main package variables
echo "PKG_NAME=$(extract_var PKG_NAME)"
echo "PKG_VERSION=$(extract_var PKG_VERSION)"
echo "PKG_SOURCE_URL=$(extract_var PKG_SOURCE_URL)"
echo "PKG_SOURCE_VERSION=$(extract_var PKG_SOURCE_VERSION)"
echo "PKG_MIRROR_HASH_OLD=$(extract_var PKG_MIRROR_HASH)"

# Extract SmartDNS WebUI variables
echo "SMARTDNS_WEBUI_VERSION=$(extract_var SMARTDNS_WEBUI_VERSION)"
echo "SMARTDNS_WEBUI_SOURCE_URL=$(extract_var SMARTDNS_WEBUI_SOURCE_URL)"
echo "SMARTDNS_WEBUI_SOURCE_VERSION=$(extract_var SMARTDNS_WEBUI_SOURCE_VERSION)"

# Extract WebUI hash from Download block (special format)
WEBUI_HASH=$(awk '/define Download\/smartdns-webui/,/endef/ { 
    if ($0 ~ /MIRROR_HASH:=/) { 
        sub(/.*MIRROR_HASH:=/, ""); 
        gsub(/^[[:space:]]+|[[:space:]]+$/, "", $0); 
        print; 
        exit 
    } 
}' "$MAKEFILE")
echo "SMARTDNS_WEBUI_HASH_OLD=$WEBUI_HASH"
