#!/usr/bin/env python3
from __future__ import annotations
"""Backfill comment entries in posted_log.json from discussions_cache.json.

Sim agents post comments via `gh api graphql`, which never writes to
posted_log.json. This script reads the already-scraped discussions cache
and adds stub comment entries for any comments not yet tracked.

Agent IDs are extracted from comment body attribution lines
(*— **agent-id***). Comments without a parseable attribution are
skipped (the GitHub login is shared by all sim agents so it cannot
identify individual agents).

Deduplicates by (discussion_number, author) — one entry per unique
author per discussion. Multiple comments by the same agent on the
same discussion are collapsed into a single log entry.

No API calls — reads only from local state files.

Usage:
    python scripts/backfill_comments.py             # backfill mode
    python scripts/backfill_comments.py --dry-run   # show what would change
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "state"

sys.path.insert(0, str(ROOT / "scripts"))
from state_io import load_json, save_json

# Attribution pattern from comment bodies: *— **agent-id***
COMMENT_AUTHOR_RE = re.compile(r"\*\u2014 \*\*([a-z0-9-]+)\*\*\*")

DRY_RUN = "--dry-run" in sys.argv


def extract_agent_id(body: str) -> str:
    """Extract agent ID from a comment body's attribution line.

    Returns empty string if no attribution found.
    """
    match = COMMENT_AUTHOR_RE.search(body or "")
    return match.group(1) if match else ""


def backfill() -> int:
    """Backfill missing comment entries from the discussions cache.

    Returns the number of new entries added.
    """
    cache = load_json(STATE_DIR / "discussions_cache.json")
    discussions = cache.get("discussions", [])
    if not discussions:
        print("[backfill] No discussions in cache, nothing to do.")
        return 0

    log = load_json(STATE_DIR / "posted_log.json")
    if not log:
        log = {"posts": [], "comments": []}
    log.setdefault("comments", [])

    # Build set of existing (discussion_number, author) pairs for dedup
    existing_keys: set[tuple[int, str]] = set()
    for comment in log["comments"]:
        key = (comment.get("discussion_number", 0), comment.get("author", ""))
        existing_keys.add(key)

    new_entries: list[dict] = []

    for disc in discussions:
        number = disc.get("number", 0)
        title = disc.get("title", "")
        channel = disc.get("category_slug", "")
        comment_authors = disc.get("comment_authors", [])

        if not comment_authors:
            continue

        # Track which agent IDs we've already added for THIS discussion
        # to avoid duplicates within the same discussion's comment list
        seen_in_disc: set[str] = set()

        for comment_entry in comment_authors:
            # Extract agent ID from body attribution
            body = comment_entry.get("body", "")
            agent_id = extract_agent_id(body)

            # Skip if no agent ID found — the GitHub login (e.g. "kody-w")
            # is shared by all sim agents so it's not useful for attribution
            if not agent_id:
                continue

            # Dedup: skip if already in posted_log or already added in this run
            key = (number, agent_id)
            if key in existing_keys or key in seen_in_disc:
                continue

            seen_in_disc.add(key)

            # Use the comment's own created_at timestamp if available,
            # otherwise fall back to the discussion's created_at
            timestamp = comment_entry.get("created_at", "") or disc.get("created_at", "")

            new_entries.append({
                "timestamp": timestamp,
                "discussion_number": number,
                "post_title": title,
                "author": agent_id,
                "channel": channel,
            })

    print(f"[backfill] Existing comment entries: {len(log['comments'])}")
    print(f"[backfill] New comment entries:      {len(new_entries)}")

    if new_entries and not DRY_RUN:
        log["comments"].extend(new_entries)
        save_json(STATE_DIR / "posted_log.json", log)
        print(f"[backfill] Total comment entries:    {len(log['comments'])}")

    if DRY_RUN and new_entries:
        print("[backfill] Dry run — no files written.")

    return len(new_entries)


def main() -> None:
    """Run comment backfill."""
    added = backfill()
    if added == 0:
        print("[backfill] Nothing to backfill.")
    else:
        print(f"[backfill] Done — {added} comment entries added.")


if __name__ == "__main__":
    main()
