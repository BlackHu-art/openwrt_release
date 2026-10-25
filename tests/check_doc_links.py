#!/usr/bin/env python3
"""Check local file links in maintained documentation, without network access.

This bounded check covers inline Markdown links and reference definitions. It
checks destination paths, not heading anchors or remote URL availability, and
does not scan vendored documentation or archived diagnostic reports.
"""
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
ENTRY_POINTS = (
    "README.md", "docs/README.md", "docs/project-layout.md",
    "docs/windows-testing.md", "docs/fw876-core-migration.md",
    "docs/plugin-compatibility.md",
    "docs/fw876-upstream-backports.md", "wrt_core/managed/README.md",
    "maintenance/plugins/README.md",
)
INLINE_LINK = re.compile(r"!?\[[^\]\n]*\]\(\s*(<[^>\n]+>|[^\s)]+)")
REFERENCE_LINK = re.compile(r"^\s{0,3}\[[^\]\n]+\]:\s*(<[^>\n]+>|\S+)")


def check_document(path):
    failures = []
    fence = None
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if marker:
            token = marker.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            continue
        if fence:
            continue
        matches = list(INLINE_LINK.finditer(line))
        reference = REFERENCE_LINK.match(line)
        if reference:
            matches.append(reference)
        for match in matches:
            target = match.group(1).strip("<>")
            # A local drive/UNC path is not portable, even on the author host.
            if re.match(r"^[A-Za-z]:", target) or "\\" in target or target.startswith("file:"):
                failures.append((number, target, "nonportable local link"))
                continue
            parts = urlsplit(target)
            if parts.scheme or parts.netloc or not parts.path:
                continue
            relative = unquote(parts.path)
            destination = ((ROOT / relative.lstrip("/")) if relative.startswith("/")
                           else (path.parent / relative)).resolve()
            if not destination.is_relative_to(ROOT):
                failures.append((number, target, "link escapes repository"))
            elif not destination.exists():
                failures.append((number, target, "missing local target"))
    return failures


def main():
    documents = [ROOT / item for item in ENTRY_POINTS]
    documents.extend(sorted((ROOT / "docs/maintenance").glob("*.md")))
    errors = []
    for document in documents:
        if not document.is_file():
            errors.append(f"{document.relative_to(ROOT)}: missing documentation entry")
            continue
        for line, target, reason in check_document(document):
            errors.append(f"{document.relative_to(ROOT)}:{line}: {reason}: {target}")
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"Documentation local file links: PASS ({len(documents)} files; anchors/remote URLs not checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
