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
from pathlib import Path

SHARD_SIZE = 250  # discussions per shard

# Fields kept in the lightweight meta shard
META_FIELDS = {
    "number", "node_id", "title", "author_login", "category_slug",
    "created_at", "url", "upvotes", "downvotes", "comment_count",
}


def shard_cache(state_dir: str | None = None) -> None:
    """Split discussions_cache.json into meta + body shards."""
    state = Path(state_dir or os.environ.get("STATE_DIR", "state"))
    cache_path = state / "discussions_cache.json"
    shard_dir = state / "cache_shards"
    shard_dir.mkdir(exist_ok=True)

    cache = json.loads(cache_path.read_text())
    discussions = cache.get("discussions", [])

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
            {k: v for k, v in d.items() if k in META_FIELDS}
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
                entry["comments"] = d["comments"]
            if d.get("comment_authors"):
                entry["comment_authors"] = d["comment_authors"]
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
