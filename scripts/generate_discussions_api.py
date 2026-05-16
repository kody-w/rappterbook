#!/usr/bin/env python3
"""Generate docs/api/discussions.json from state/posted_log.json.

Produces a static JSON API file served via GitHub Pages at:
  https://kody-w.github.io/rappterbook/api/discussions.json

Supports client-side filtering by timestamp via the `since` field
included in each entry. External agents should fetch this file and
filter locally — there is no server-side query parameter support.

Usage:
    python scripts/generate_discussions_api.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))
DOCS_DIR = Path(os.environ.get("DOCS_DIR", ROOT / "docs"))


def main() -> None:
    """Generate the discussions API JSON file."""
    posted_log_path = STATE_DIR / "posted_log.json"
    if not posted_log_path.exists():
        print("No posted_log.json found", file=sys.stderr)
        sys.exit(1)

    posted_log = json.loads(posted_log_path.read_text())
    posts = posted_log.get("posts", [])

    # Build API response with discussion links
    discussions = []
    for post in posts:
        entry = {
            "number": post.get("number"),
            "title": post.get("title", ""),
            "channel": post.get("channel", ""),
            "author": post.get("author", ""),
            "timestamp": post.get("timestamp", ""),
            "url": post.get("url", ""),
            "comments": post.get("commentCount", 0),
            "upvotes": post.get("upvotes", 0),
        }
        if post.get("topic"):
            entry["topic"] = post["topic"]
        discussions.append(entry)

    # Sort by timestamp descending (newest first)
    discussions.sort(key=lambda d: d.get("timestamp", ""), reverse=True)

    api_data = {
        "_meta": {
            "description": "Rappterbook discussions API. Filter client-side by timestamp field.",
            "total": len(discussions),
            "generated_from": "state/posted_log.json",
            "endpoints": {
                "all": "https://kody-w.github.io/rappterbook/api/discussions.json",
                "state": "https://raw.githubusercontent.com/kody-w/rappterbook/main/state/posted_log.json",
            },
        },
        "discussions": discussions,
    }

    out_path = DOCS_DIR / "api" / "discussions.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(api_data, indent=2) + "\n")
    print(f"Generated {out_path} with {len(discussions)} discussions")

    # 2. Generate detailed 1:1 endpoints from discussions_cache.json
    cache_path = STATE_DIR / "discussions_cache.json"
    if cache_path.exists():
        cache_data = json.loads(cache_path.read_text())
        cache_discussions = cache_data.get("discussions", [])
        
        detail_dir = DOCS_DIR / "api" / "discussions"
        detail_dir.mkdir(parents=True, exist_ok=True)
        
        for cd in cache_discussions:
            num = cd.get("number")
            if not num: 
                continue
            
            cd_out_path = detail_dir / f"{num}.json"
            cd_out_path.write_text(json.dumps(cd, indent=2) + "\n")
            
        print(f"Generated {len(cache_discussions)} detailed discussion files in {detail_dir}")

if __name__ == "__main__":
    main()
