#!/usr/bin/env python3
"""Prepare Aurora build-copy defaults that preserve retained user settings."""
import argparse
import hashlib
import os
from pathlib import Path
import re
import sys
import tempfile


RAW = Path(__file__).resolve().parent / "managed/packages/luci-app-aurora-config"
INITIALIZER = "root/etc/uci-defaults/80_aurora"
REVIEWED_SHA256 = "dfaed69ddee7460bad0c5cf88c40b1b2d3278c61813d453bc0590219d4555b46"

MIGRATION = r'''# Existing explicit and unknown options always win over template defaults.
# Copy legacy names only where their same-meaning replacement is absent. Keep
# the original key too, so a conflicting value is never irreversibly discarded.
copy_missing_option() {
    local old="$1" new="$2" value
    uci -q get "aurora.theme.$new" >/dev/null 2>&1 && return 0
    value=$(uci -q get "aurora.theme.$old") || return 0
    uci -q set "aurora.theme.$new=$value"
}

migrate_structure_keys() {
    uci -q get aurora.theme.struct_content_width_centered >/dev/null 2>&1 && return 0
    uci -q get aurora.theme.struct_container_max_width >/dev/null 2>&1 || return 0
    copy_missing_option struct_container_max_width struct_content_width_centered || return 1
    uci -q commit aurora
}

clear_template_defaults() {
    rm -f "$1/aurora" "$1/keys"
    rmdir "$1"
}

migrate_color_schema() {
    local template="$1" stored defaults_dir entry key value

    stored=$(uci -q get aurora.theme.config_version)
    case "$stored" in
        "$SCHEMA_VERSION") return 0 ;;
        ''|0|1|2|3|4|5|6) ;;
        *) log "Unknown schema '$stored'; preserving configuration without downgrade"; return 1 ;;
    esac

    defaults_dir=$(mktemp -d /tmp/aurora-defaults.XXXXXX) || return 1
    if ! cp "$template" "$defaults_dir/aurora" ||
       ! uci -c "$defaults_dir" -q show aurora.theme > "$defaults_dir/keys"; then
        clear_template_defaults "$defaults_dir"
        return 1
    fi

    uci -q get aurora.theme >/dev/null 2>&1 ||
        uci -q set aurora.theme=aurora || { clear_template_defaults "$defaults_dir"; return 1; }

    copy_missing_option struct_container_max_width struct_content_width_centered &&
    copy_missing_option light_canvas light_bg &&
    copy_missing_option dark_canvas dark_bg &&
    copy_missing_option light_content light_text &&
    copy_missing_option dark_content dark_text || { clear_template_defaults "$defaults_dir"; return 1; }

    # Read the immutable template via UCI, without evaluating shell-quoted data.
    # Only the named theme section receives missing scalar defaults. Anonymous
    # toolbar entries and unrelated/unknown sections retain their values.
    while IFS= read -r entry; do
        case "$entry" in aurora.theme.*=*) key=${entry%%=*}; key=${key#aurora.theme.} ;; *) continue ;; esac
        if ! uci -q get "aurora.theme.$key" >/dev/null 2>&1; then
            value=$(uci -c "$defaults_dir" -q get "aurora.theme.$key") &&
                uci -q set "aurora.theme.$key=$value" || { clear_template_defaults "$defaults_dir"; return 1; }
        fi
    done < "$defaults_dir/keys"
    clear_template_defaults "$defaults_dir"
    uci -q set aurora.theme.config_version="$SCHEMA_VERSION" &&
        uci -q commit aurora || return 1
    log "Schema v$SCHEMA_VERSION defaults completed; existing settings preserved"
}

'''


def _prepared(raw):
    text = raw.decode("utf-8")
    text, count = re.subn(r"# Bump when the meaning.*?(?=readonly SCHEMA_VERSION)",
                          "# Schema defaults are filled without resetting retained settings.\n", text, count=1, flags=re.S)
    if count != 1:
        raise ValueError("Aurora reviewed schema declaration changed")
    start, end = text.index("# Rename struct_container_max_width"), text.index("main() {")
    text = text[:start] + MIGRATION + text[end:]
    old = '''        migrate_color_schema "$template"
        # After a reset the config already matches the template, so this is a
        # no-op; it only does work for configs that survived the check above.
        migrate_structure_keys'''
    if text.count(old) != 1:
        raise ValueError("Aurora reviewed migration callsite changed")
    text = text.replace(old, '''        if migrate_color_schema "$template"; then
            migrate_structure_keys
        fi''')
    return text.encode("utf-8")


def prepare_aurora_config(package_dir):
    """Accept complete raw/prepared initializer bytes in a separate build copy."""
    package_dir = Path(package_dir)
    root = package_dir.resolve()
    if not package_dir.is_dir() or root.is_relative_to(RAW.resolve()):
        raise ValueError("Aurora preparation requires a separate build copy")
    raw = (RAW / INITIALIZER).read_bytes()
    if hashlib.sha256(raw).hexdigest() != REVIEWED_SHA256:
        raise ValueError("Aurora managed initializer has unreviewed source drift")
    expected = _prepared(raw)
    target = package_dir / INITIALIZER
    if target.is_symlink() or not target.is_file() or not target.resolve().is_relative_to(root):
        raise ValueError("Aurora initializer is missing or redirected outside the build copy")
    current = target.read_bytes()
    if current == expected:
        return
    if current != raw:
        raise ValueError("Aurora build initializer has unreviewed or partial source changes")
    descriptor, temporary = tempfile.mkstemp(prefix="80_aurora.compat-", dir=target.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(expected)
        os.chmod(temporary, target.stat().st_mode & 0o777)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package_dir", type=Path)
    arguments = parser.parse_args(argv)
    try:
        prepare_aurora_config(arguments.package_dir)
    except (OSError, ValueError) as error:
        print(f"Aurora compatibility preparation failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
