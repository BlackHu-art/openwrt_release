#!/usr/bin/env python3
"""Focused UCI filesystem boundary for the real SSR defaults-hook tests.

Only section/option/list syntax and the hook's get/set/delete/add/commit are
represented. Named mutations remain pending until commit writes the real
configuration file; absolute validation bypasses overrides and pending state.
This is not a substitute for target UCI/package-manager acceptance.
"""
import json
import os
from pathlib import Path
import re
import shlex
import sys


def read_config(path):
    sections = {}
    current = None
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = shlex.split(line, comments=True)
        if not fields:
            continue
        if fields[0] == "config" and len(fields) in (2, 3):
            sid = fields[2] if len(fields) == 3 else "anonymous" + str(len(sections))
            current = sections[sid] = {".type": fields[1], ".anonymous": len(fields) == 2}
        elif current is not None and fields[0] in ("option", "list") and len(fields) == 3:
            if fields[0] == "list":
                current.setdefault(fields[1], []).append(fields[2])
            else:
                current[fields[1]] = fields[2]
        else:
            raise ValueError("invalid fixture UCI syntax: " + line)
    return sections


def write_config(path, sections):
    lines = []
    for sid, values in sections.items():
        lines.append("config " + values[".type"] + ("" if values.get(".anonymous") else " " + shlex.quote(sid)))
        for key, value in values.items():
            if not key.startswith("."):
                for item in value if isinstance(value, list) else [value]:
                    # Keep UCI's quoted spelling so the actual upstream sed
                    # conversions run against the same syntax as target UCI.
                    quoted = "'" + item.replace("'", "'\\''") + "'"
                    lines.append("\t" + ("list" if isinstance(value, list) else "option") + " " + key + " " + quoted)
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def main():
    root = Path(os.environ["TEST_HOST_ROOT"])
    with (root / "uci-calls").open("a", encoding="utf-8") as calls:
        calls.write(" ".join(sys.argv[1:]) + "\n")
    args = sys.argv[1:]
    directory = None
    while args and args[0].startswith("-"):
        flag = args.pop(0)
        if flag == "-c":
            directory = args.pop(0)
        elif flag != "-q":
            raise AssertionError("unexpected UCI flag: " + flag)
    operation, *args = args
    if operation == "batch":
        data = sys.stdin.read()
        assert all(not line.strip() or line.split()[1].split(".")[0] in ("firewall", "ucitrack")
                   for line in data.splitlines()), "unexpected hook batch"
        with (root / "uci-batch").open("a", encoding="utf-8") as batch:
            batch.write(data)
        return 0
    target = args[0]
    if operation == "get" and os.environ.get("FAIL_UCI") == "1":
        return 1
    if target.startswith("/"):
        prefix = os.environ["TEST_ROOT"] + "/fs/etc/config/"
        relative = target.removeprefix(prefix).removesuffix(".@global[0]")
        assert target.startswith(prefix) and re.fullmatch(r"ssrplus-init-[A-Za-z0-9]+/shadowsocksr", relative)
        path = root / "fs/etc/config" / relative
        with (root / "uci-validation-files").open("a", encoding="utf-8") as calls:
            calls.write(target.removesuffix(".@global[0]") + "\n")
        sections = read_config(path)
        valid = any(value[".type"] == "global" for value in sections.values())
        if valid:
            print("global")
        return 0 if valid else 1
    assert target == "shadowsocksr" or target.startswith("shadowsocksr."), target
    path = root / "fs/etc/config/shadowsocksr"
    state = root / "uci-pending.json"
    sections = json.loads(state.read_text()) if state.exists() else read_config(path)
    if operation == "add":
        sid = "anonymous" + str(len(sections))
        sections[sid] = {".type": args[1], ".anonymous": True}
        print(sid)
    elif operation == "commit":
        write_config(path, sections)
        state.unlink(missing_ok=True)
        return 0
    else:
        tuple_, separator, value = target.partition("=")
        fields = tuple_.split(".")
        selector = fields[1]
        key = fields[2] if len(fields) == 3 else None
        if selector.startswith("@"):
            match = re.fullmatch(r"@(\w+)\[(-?\d+)\]", selector)
            assert match, selector
            matches = [sid for sid, data in sections.items() if data[".type"] == match[1]]
            try:
                selector = matches[int(match[2])]
            except IndexError:
                return 1
        section = sections.get(selector)
        if section is None:
            return 1
        if operation == "get":
            result = section.get(key) if key else section[".type"]
            if result is None:
                return 1
            print(" ".join(result) if isinstance(result, list) else result)
            return 0
        if operation == "set":
            assert separator and key, target
            section[key] = value
        elif operation == "delete":
            if key:
                section.pop(key, None)
            else:
                sections.pop(selector)
        else:
            raise AssertionError("unexpected UCI operation: " + operation)
    state.write_text(json.dumps(sections), encoding="utf-8")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError):
        sys.exit(1)
