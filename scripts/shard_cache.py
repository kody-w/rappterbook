#!/usr/bin/env python3
from __future__ import annotations
"""Shard discussions_cache.json into ~1000-discussion chunks.

Produces state/cache_shards/shard_NNNNN.json files keyed by discussion
number range (0-999, 1000-1999, etc.) plus an index file that maps
shard boundaries for O(1) lookup.

Usage:
    python scripts/shard_cache.py
"""
import json
import os
from pathlib import Path

SHARD_SIZE = 250  # discussions per shard


def shard_cache(state_dir: str | None = None) -> None:
    """Split discussions_cache.json into numbered shards."""
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

    # Write each shard
    index = {}
    for bucket, items in sorted(buckets.items()):
        shard_name = f"shard_{bucket:05d}.json"
        shard_path = shard_dir / shard_name
        shard_data = {
            "_meta": {
                "range_start": bucket,
                "range_end": bucket + SHARD_SIZE - 1,
                "count": len(items),
            },
            "discussions": sorted(items, key=lambda d: d.get("number", 0)),
        }
        shard_path.write_text(json.dumps(shard_data, separators=(",", ":")))
        size_kb = shard_path.stat().st_size // 1024
        index[str(bucket)] = {
            "file": shard_name,
            "count": len(items),
            "size_kb": size_kb,
        }
        print(f"  {shard_name}: {len(items)} discussions, {size_kb}KB")

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


if __name__ == "__main__":
    shard_cache()
