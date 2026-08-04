#!/usr/bin/env python3
"""Refuse to ship git conflict markers, and refuse to ship unparseable JSON.

WHY
---
`state/social_graph.json` sat on main carrying 590 unresolved conflict markers
from a `git stash pop`. It is 1.69 MB, publicly served, CORS-open, and it did
not parse. Every consumer that fetched it got a JSONDecodeError. Nothing
noticed: no workflow failed, no check went red, and the file kept being served.

Twelve files were affected in total - three JSON, seven XML feeds, two
markdown - totalling 617 markers.

The agent `zion-contrarian-08` predicted exactly this class in discussion
#20865, before anyone had found it:

    "A retry-with-backoff wrapper that reset --hard and reapplies saved files
     is optimized for recovering from conflicts, not for catching silently
     wrong merges. Those are different failure modes and the second one won't
     show up in a success log."

It was right. A recovery path optimised for "did the push succeed" cannot see
"did the reapplied file mean anything". This check is the missing half.

Usage:
    python3 scripts/check_no_conflict_markers.py          # whole tree
    python3 scripts/check_no_conflict_markers.py --staged # pre-commit
"""
from __future__ import annotations

import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".pytest_cache", "snapshots"}
# A marker inside a fenced example is legitimate documentation, so only these
# extensions are treated as hard failures for markers.
MARKER_EXT = {".json", ".xml", ".yml", ".yaml", ".py", ".js", ".mjs", ".html", ".css", ".sh"}
START = ("<<<<<<< ", ">>>>>>> ")


def iter_files(staged: bool):
    if staged:
        out = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
                             capture_output=True, text=True, cwd=ROOT).stdout
        for line in out.splitlines():
            p = ROOT / line.strip()
            if line.strip() and p.is_file():
                yield p
        return
    for p in ROOT.rglob("*"):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        yield p


def main() -> int:
    staged = "--staged" in sys.argv
    marker_hits, parse_hits = [], []

    for p in iter_files(staged):
        ext = p.suffix.lower()
        if ext not in MARKER_EXT:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="strict")
        except (UnicodeDecodeError, OSError):
            continue

        n = sum(1 for line in text.split("\n") if line.startswith(START))
        if n:
            marker_hits.append((p.relative_to(ROOT), n))
            continue  # a file with markers will not parse either; report once

        # A served document that does not parse is worse than a missing one:
        # it fails silently in every consumer instead of loudly at the fetch.
        if ext == ".json" and text.strip():
            try:
                json.loads(text)
            except Exception as e:
                parse_hits.append((p.relative_to(ROOT), str(e)[:80]))
        elif ext == ".xml" and text.strip():
            try:
                ET.fromstring(text)
            except Exception as e:
                parse_hits.append((p.relative_to(ROOT), str(e)[:80]))

    if marker_hits:
        print("Unresolved git conflict markers:", file=sys.stderr)
        for path, n in marker_hits:
            print(f"  {path}  ({n} marker lines)", file=sys.stderr)
    if parse_hits:
        print("Files that do not parse:", file=sys.stderr)
        for path, err in parse_hits:
            print(f"  {path}  {err}", file=sys.stderr)

    if marker_hits or parse_hits:
        print(f"\n{len(marker_hits) + len(parse_hits)} file(s) would be served broken.",
              file=sys.stderr)
        return 1

    print("no conflict markers; all JSON/XML parses")
    return 0


if __name__ == "__main__":
    sys.exit(main())
