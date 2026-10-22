#!/bin/bash
#
# Download source from git and create reproducible tarball
# Usage: download-and-package.sh <pkg_name> <pkg_version> <source_url> <source_version> <file_extension> <output_dir>
#
# Supports:
#   .tar.gz  - gzip compressed (for webui)
#   .tar.zst - zstd compressed (for smartdns main)
#

set -euo pipefail

PKG_NAME="$1"
PKG_VERSION="$2"
PKG_SOURCE_URL="$3"
PKG_SOURCE_VERSION="$4"
FILE_EXTENSION="$5"
OUTPUT_DIR="$(realpath -m "${6:-.}")"

HOST_TAR="${HOST_TAR:-tar}"
HOST_ZSTD="${HOST_ZSTD:-zstd}"
HOST_GZ="${HOST_GZ:-gzip}"

OUTPUT_FILENAME="${PKG_NAME}-${PKG_VERSION}${FILE_EXTENSION}"

case "${FILE_EXTENSION}" in
    .tar.gz)
        COMPRESSOR="${HOST_GZ} -n"
        SUBDIR="${PKG_NAME}"
        ;;
    .tar.zst)
        COMPRESSOR="${HOST_ZSTD} -T0 --ultra -20"
        SUBDIR="${PKG_NAME}-${PKG_VERSION}"
        ;;
    *)
        echo "ERROR: Unknown compression format: ${FILE_EXTENSION}" >&2
        exit 1
        ;;
esac

echo "==> Processing ${PKG_NAME} v${PKG_VERSION}..."
echo "    Source: ${PKG_SOURCE_URL}"
echo "    Version: ${PKG_SOURCE_VERSION}"
echo "    Output: ${OUTPUT_DIR}/${OUTPUT_FILENAME}"

# Create temporary directory
TMP_DIR=$(mktemp -d)
trap "rm -rf '${TMP_DIR}'" EXIT

pushd "${TMP_DIR}" > /dev/null

# Clone and checkout specific version
echo "==> Cloning repository..."
git clone --filter=blob:none "${PKG_SOURCE_URL}" "${SUBDIR}"
(cd "${SUBDIR}" && git checkout "${PKG_SOURCE_VERSION}")

# Get timestamp from git commit for reproducible builds
export TAR_TIMESTAMP=$(cd "${SUBDIR}" && git log -1 --no-show-signature --format='%ct')

# Create git archive
echo "==> Creating archive..."
(cd "${SUBDIR}" && git config core.abbrev 8 && git archive --format=tar HEAD --output="../${SUBDIR}.tar.git")

# Append .git and .gitmodules to archive (for submodule handling)
"${HOST_TAR}" --numeric-owner --owner=0 --group=0 --ignore-failed-read -C "${SUBDIR}" -f "${SUBDIR}.tar.git" -r .git .gitmodules 2>/dev/null || true

# Extract and handle submodules
rm -rf "${SUBDIR}" && mkdir "${SUBDIR}"
"${HOST_TAR}" -C "${SUBDIR}" -xf "${SUBDIR}.tar.git"
(cd "${SUBDIR}" && git submodule update --init --recursive -- && rm -rf .git .gitmodules) 2>/dev/null || true

# Create final reproducible tarball
echo "==> Compressing with ${COMPRESSOR}..."
"${HOST_TAR}" --numeric-owner --owner=0 --group=0 --mode=a-s --sort=name --mtime="@${TAR_TIMESTAMP}" -c "${SUBDIR}" | ${COMPRESSOR} -c > "${OUTPUT_FILENAME}"

# Move to output directory
mkdir -p "${OUTPUT_DIR}"
mv -f "${OUTPUT_FILENAME}" "${OUTPUT_DIR}/"

popd > /dev/null

echo "==> Done: ${OUTPUT_DIR}/${OUTPUT_FILENAME}"
