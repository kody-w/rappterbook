#!/usr/bin/env python3
"""Build a vault.json index for the Obsidian twin viewer.

Walks docs/obsidian/, extracts frontmatter + body + wikilinks, writes
docs/obsidian/vault.json. The online viewer (docs/rappter-obsidian.html)
loads this file to render notes + graph.
"""
from __future__ import annotations
import json
import re
from pathlib import Path

VAULT = Path(__file__).resolve().parent.parent / "docs" / "obsidian"
OUT = VAULT / "vault.json"

WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|([^\]]+))?\]\]")
FM_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)


def parse_frontmatter(text: str) -> tuple[dict, str]:
    m = FM_RE.match(text)
    if not m:
        return {}, text
    fm_block, body = m.groups()
    fm: dict = {}
    for line in fm_block.splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        fm[key.strip()] = val.strip()
    return fm, body


def extract_links(body: str) -> list[str]:
    out = []
    for m in WIKILINK_RE.finditer(body):
        target = m.group(1).strip()
        if target not in out:
            out.append(target)
    return out


def main() -> int:
    notes = {}
    for path in VAULT.rglob("*.md"):
        rel = path.relative_to(VAULT).as_posix()
        name = path.stem
        text = path.read_text()
        fm, body = parse_frontmatter(text)
        notes[name] = {
            "name": name,
            "path": rel,
            "folder": rel.split("/")[0] if "/" in rel else "",
            "frontmatter": fm,
            "body": body,
            "links": extract_links(body),
        }

    # Build backlinks
    for name, note in notes.items():
        note["backlinks"] = [
            other for other, odata in notes.items()
            if name in odata["links"] and other != name
        ]

    index = {
        "_meta": {
            "note_count": len(notes),
            "generator": "scripts/build_obsidian_index.py",
        },
        "notes": notes,
    }
    OUT.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {OUT} ({len(notes)} notes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
