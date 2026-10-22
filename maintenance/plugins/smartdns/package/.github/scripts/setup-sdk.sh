#!/bin/bash
#
# Download and setup OpenWrt/ImmortalWrt SDK
# Usage: setup-sdk.sh <sdk_type>
#
# Arguments:
#   sdk_type: 'openwrt' or 'immortalwrt'
#
# Outputs to GITHUB_ENV:
#   HOST_TAR, HOST_ZSTD, HOST_GZ - paths to toolchain binaries
#

set -euo pipefail

SDK_TYPE="${1:-immortalwrt}"
SDK_DIR="${2:-sdk}"

case "${SDK_TYPE}" in
    openwrt)
        SDK_BASE_URL="https://downloads.openwrt.org/snapshots/targets/x86/64/"
        ;;
    immortalwrt)
        SDK_BASE_URL="https://downloads.immortalwrt.org/snapshots/targets/x86/64/"
        ;;
    *)
        echo "ERROR: Unsupported SDK type: ${SDK_TYPE}" >&2
        echo "Supported types: openwrt, immortalwrt" >&2
        exit 1
        ;;
esac

echo "==> Setting up SDK for ${SDK_TYPE}..."
echo "    Base URL: ${SDK_BASE_URL}"

# Find SDK filename from download page
SDK_FILENAME=$(wget -q -O - "${SDK_BASE_URL}" | grep -oP "${SDK_TYPE}-sdk.*\.tar\.zst" | awk -F'>' '{print $NF}' | head -n 1)

if [[ -z "${SDK_FILENAME}" ]]; then
    echo "ERROR: Could not find SDK filename on ${SDK_BASE_URL}" >&2
    exit 1
fi

echo "==> Found latest SDK: ${SDK_FILENAME}"

# Download SDK
echo "==> Downloading SDK..."
wget -q --show-progress "${SDK_BASE_URL}${SDK_FILENAME}"

# Extract SDK
echo "==> Extracting SDK..."
mkdir -p "${SDK_DIR}"
zstd -d -c "${SDK_FILENAME}" | tar -xf - -C "${SDK_DIR}" --strip-components=1

# Clean up downloaded archive
rm -f "${SDK_FILENAME}"

echo "==> SDK setup complete."

# Find and output toolchain paths
HOST_DIR=$(find "${SDK_DIR}/staging_dir" -type d -name "host" | head -n 1)

if [[ -z "${HOST_DIR}" ]]; then
    echo "ERROR: Could not find the 'host' directory in the SDK." >&2
    exit 1
fi

echo "==> Found host directory at ${HOST_DIR}"

HOST_TAR="$(realpath "${HOST_DIR}/bin/tar")"
HOST_ZSTD="$(realpath "${HOST_DIR}/bin/zstd")"
HOST_GZ="$(realpath "${HOST_DIR}/bin/gzip")"

# Output to GITHUB_ENV if available
if [[ -n "${GITHUB_ENV:-}" ]]; then
    echo "HOST_TAR=${HOST_TAR}" >> "${GITHUB_ENV}"
    echo "HOST_ZSTD=${HOST_ZSTD}" >> "${GITHUB_ENV}"
    echo "HOST_GZ=${HOST_GZ}" >> "${GITHUB_ENV}"
fi

# Also print for local testing
echo "HOST_TAR=${HOST_TAR}"
echo "HOST_ZSTD=${HOST_ZSTD}"
echo "HOST_GZ=${HOST_GZ}"
