#!/usr/bin/env bash
# Compile the production firmware's actual upstream conf, then run the same
# generated-metadata behavioral cases against that binary. Never accept a skip
# in a required Linux CI job. Generated lexer/parser files are vendored as-is.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
if [[ $(uname -s) != Linux ]]; then
    if [[ ${REQUIRE_KCONFIG_CONF:-0} == 1 ]]; then
        echo "ERROR: required upstream Kconfig conf gate needs Linux" >&2
        exit 1
    fi
    echo "SKIP: upstream Kconfig conf gate needs Linux; kconfiglib is tested separately"
    exit 0
fi
for executable in gcc make perl python3; do
    command -v "$executable" >/dev/null || {
        echo "ERROR: upstream Kconfig conf gate requires $executable" >&2
        exit 1
    }
done
WORK=$(mktemp -d)
trap 'rm -rf -- "$WORK"' EXIT
cp -R "$ROOT/tests/fixtures/kconfig-compat/immortalwrt/scripts/config" "$WORK/config"
make --no-print-directory -s -C "$WORK/config" CC=gcc conf
export KCONFIG_CONF="$WORK/config/conf"
export PYTHONDONTWRITEBYTECODE=1
python3 "$ROOT/tests/test_kconfig_compat.py"
