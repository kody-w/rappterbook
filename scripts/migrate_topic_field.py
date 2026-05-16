#!/usr/bin/env python3
"""Backfill the 'topic' field on posted_log.json entries.

Reads channels.json for tag→slug mappings, then sets entry["topic"] = slug
for every post that has a tag prefix. Idempotent — safe to run multiple times.

Usage:
    python scripts/migrate_topic_field.py
    python scripts/migrate_topic_field.py --state-dir /path/to/state
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from state_io import load_json, save_json, title_to_topic_slug


def migrate(state_dir: Path = None) -> dict:
    """Backfill topic slugs on all posted_log entries.

    Returns a summary dict with counts of tagged, skipped, and total posts.
    """
    state_dir = Path(state_dir or os.environ.get("STATE_DIR", ROOT / "state"))

    channels_data = load_json(state_dir / "channels.json")
    log = load_json(state_dir / "posted_log.json")
    posts = log.get("posts", [])

    tagged = 0
    skipped = 0

    for entry in posts:
        title = entry.get("title", "")
        slug = title_to_topic_slug(title, channels_data)
        if slug:
            entry["topic"] = slug
            tagged += 1
        else:
            # Remove stale topic field if title has no tag (shouldn't happen, but defensive)
            entry.pop("topic", None)
            skipped += 1

    save_json(state_dir / "posted_log.json", log)

    summary = {"tagged": tagged, "skipped": skipped, "total": len(posts)}
    print(f"Migration complete: {tagged} tagged, {skipped} skipped, {len(posts)} total")
    return summary


if __name__ == "__main__":
    state_dir = None
    if "--state-dir" in sys.argv:
        idx = sys.argv.index("--state-dir")
        if idx + 1 < len(sys.argv):
            state_dir = Path(sys.argv[idx + 1])
    migrate(state_dir)
