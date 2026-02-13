#!/usr/bin/env python3
"""Compute trending discussions based on recent activity.

Scoring: posts (3x) + comments (2x) + reactions (1x) with recency decay.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))


def load_json(path):
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def now_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def hours_since(iso_ts):
    try:
        ts = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - ts
        return max(0, delta.total_seconds() / 3600)
    except (ValueError, TypeError):
        return 999


def compute_score(disc):
    posts = disc.get("posts_24h", 0)
    comments = disc.get("comments_24h", 0)
    reactions = disc.get("reactions_24h", 0)
    raw_score = (posts * 3) + (comments * 2) + (reactions * 1)
    hours = hours_since(disc.get("created_at", "2020-01-01T00:00:00Z"))
    decay = 1.0 / (1.0 + hours / 24.0)
    return round(raw_score * decay, 2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-file", help="Discussion data JSON file")
    args = parser.parse_args()

    discussions = []
    if args.data_file:
        data = load_json(Path(args.data_file))
        discussions = data.get("discussions", [])

    trending = []
    for disc in discussions:
        score = compute_score(disc)
        trending.append({
            "discussion_id": disc.get("id"),
            "channel": disc.get("channel", ""),
            "title": disc.get("title", ""),
            "score": score,
            "posts_24h": disc.get("posts_24h", 0),
            "comments_24h": disc.get("comments_24h", 0),
        })

    trending.sort(key=lambda x: x["score"], reverse=True)

    result = {
        "trending": trending,
        "last_computed": now_iso(),
    }

    save_json(STATE_DIR / "trending.json", result)
    print(f"Computed trending: {len(trending)} items")
    return 0


if __name__ == "__main__":
    sys.exit(main())
