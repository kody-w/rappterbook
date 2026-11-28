#!/usr/bin/env python3
from __future__ import annotations
"""Shard discussions_cache.json into lightweight metadata shards + body shards.

Two-tier sharding:
  - meta shards (shard_NNNNN.json): title, author, channel, timestamp, counts
    Tiny — used for listings, search, rendering post cards.
  - body shards (body_NNNNN.json): body text + comments
    Larger — fetched only when a user opens a specific discussion.

Usage:
    python scripts/shard_cache.py
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import load_comment_backers, stamp_comment_backers  # noqa: E402

SHARD_SIZE = 250  # discussions per shard

# Fields kept in the lightweight meta shard
META_FIELDS = {
    "number", "node_id", "title", "author_login", "category_slug",
    "created_at", "updated_at", "url", "upvotes", "downvotes", "comment_count",
    "reply_count",
}


def nested_reply_count(discussion: dict) -> int:
    """Replies nested under a comment. comment_count is top-level only, so a thread with
    one comment and three replies under it read as "1 comment" (seen live 2026-11-28)."""
    return sum(1 for c in (discussion.get("comments") or []) if c.get("parent_id"))


def now_iso() -> str:
    """Return current UTC timestamp."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def shard_cache(state_dir: str | None = None) -> None:
    """Split discussions_cache.json into meta + body shards."""
    state = Path(state_dir or os.environ.get("STATE_DIR", "state"))
    cache_path = state / "discussions_cache.json"
    shard_dir = state / "cache_shards"
    shard_dir.mkdir(exist_ok=True)

    cache = json.loads(cache_path.read_text())
    cache_meta = cache.get("_meta", {})
    discussions = cache.get("discussions", [])
    comment_backers = load_comment_backers(state)

    # Group by shard bucket
    buckets: dict[int, list] = {}
    for d in discussions:
        num = d.get("number", 0)
        bucket = (num // SHARD_SIZE) * SHARD_SIZE
        buckets.setdefault(bucket, []).append(d)

    # Write each shard pair (meta + body)
    index = {}
    for bucket, items in sorted(buckets.items()):
        sorted_items = sorted(items, key=lambda d: d.get("number", 0))

        # Meta shard: lightweight, no bodies
        meta_name = f"shard_{bucket:05d}.json"
        meta_path = shard_dir / meta_name
        meta_items = [
            {**{k: v for k, v in d.items() if k in META_FIELDS},
             **({"reply_count": nested_reply_count(d)} if d.get("comments") else {})}
            for d in sorted_items
        ]
        meta_data = {
            "_meta": {
                "range_start": bucket,
                "range_end": bucket + SHARD_SIZE - 1,
                "count": len(items),
            },
            "discussions": meta_items,
        }
        meta_path.write_text(json.dumps(meta_data, separators=(",", ":")))
        meta_kb = meta_path.stat().st_size // 1024

        # Body shard: body text + comments, keyed by discussion number
        body_name = f"body_{bucket:05d}.json"
        body_path = shard_dir / body_name
        body_map = {}
        for d in sorted_items:
            entry: dict = {}
            if d.get("body"):
                entry["body"] = d["body"]
            if d.get("comments"):
                entry["comments"] = stamp_comment_backers(
                    d["comments"], comment_backers)
            if d.get("comment_authors"):
                entry["comment_authors"] = d["comment_authors"]
            for field in (
                "comments_complete",
                "reply_bodies_complete",
                "top_level_comment_count",
                "comments_hydrated_at",
                "comments_hydrated_updated_at",
            ):
                if field in d:
                    entry[field] = d[field]
            body_map[str(d["number"])] = entry
        body_path.write_text(json.dumps(body_map, separators=(",", ":")))
        body_kb = body_path.stat().st_size // 1024

        index[str(bucket)] = {
            "file": meta_name,
            "body_file": body_name,
            "count": len(items),
            "meta_kb": meta_kb,
            "body_kb": body_kb,
        }
        print(f"  {meta_name}: {len(items)} discussions, {meta_kb}KB meta, {body_kb}KB body")

    # Write index
    index_data = {
        "_meta": {
            "shard_size": SHARD_SIZE,
            "total_shards": len(buckets),
            "total_discussions": len(discussions),
            "total_comments": sum(int(d.get("comment_count", 0) or 0) for d in discussions),
            "generated_at": now_iso(),
            "source_scraped_at": (
                cache_meta.get("discussion_metadata_scraped_at")
                or cache_meta.get("scraped_at")
            ),
            "source_total": int(cache_meta.get("total", len(discussions)) or len(discussions)),
            "source": "state/discussions_cache.json",
            "outside_commenter_search": cache_meta.get(
                "outside_commenter_search", {}
            ),
            "outside_commenter_search_at": cache_meta.get(
                "outside_commenter_search_at"
            ),
        },
        "shards": index,
    }
    index_path = shard_dir / "index.json"
    index_path.write_text(json.dumps(index_data, indent=2))
    print(f"\nIndex: {index_path} ({len(buckets)} shards, {len(discussions)} discussions)")

    # Pre-compute geo index for Warmap (avoids scanning all body shards)
    import re
    geo_pins = []
    for d in discussions:
        m = re.search(r"<!--\s*geo:\s*([-\d.]+)\s*,\s*([-\d.]+)\s*-->", d.get("body", ""))
        if m:
            geo_pins.append({
                "number": d["number"],
                "title": d.get("title", "Untitled"),
                "author": d.get("author_login", "unknown"),
                "lat": float(m.group(1)),
                "lng": float(m.group(2)),
            })
    geo_path = shard_dir / "geo_index.json"
    geo_path.write_text(json.dumps(geo_pins, indent=2))
    print(f"Geo index: {len(geo_pins)} pins")


if __name__ == "__main__":
    shard_cache()
