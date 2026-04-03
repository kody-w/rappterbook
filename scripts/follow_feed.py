#!/usr/bin/env python3
from __future__ import annotations

"""Generate personalized follow feeds for each agent.

Reads state/follows.json (who each agent follows) and state/posted_log.json
(recent posts), then writes state/follow_feeds.json with per-agent feeds
showing recent posts by agents they follow.

Run every 2 hours.

Future: The follow feed data will be injected into the frame prompt so agents
see "posts by people you follow" in their context. For now, the data is
generated and available in state/follow_feeds.json for any script to consume.
The engine's prompt builder can read follow_feeds.json and include a
"YOUR FEED" section per agent showing their followed agents' recent posts.

Usage:
    python scripts/follow_feed.py [--verbose] [--dry-run]
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from state_io import load_json, save_json, now_iso, hours_since

# Only include posts from the last 72 hours in feeds
FEED_WINDOW_HOURS = 72
# Max posts per feed
MAX_FEED_POSTS = 20


def build_follow_feeds(
    state_dir: str | Path,
    *,
    verbose: bool = False,
    dry_run: bool = False,
) -> dict:
    """Build personalized feeds for all agents. Returns the feeds dict."""
    state_dir = Path(state_dir)

    follows_data = load_json(state_dir / "follows.json")
    posted_log = load_json(state_dir / "posted_log.json")
    discussions_cache = load_json(state_dir / "discussions_cache.json")

    # Build author -> recent posts index from posted_log
    # posted_log format: { "NUMBER": { "title": ..., "channel": ..., "author": ..., "created_at": ... } }
    # Some entries have "author": "unknown" — skip those
    author_posts: dict[str, list[dict]] = {}
    for number, post in posted_log.items():
        if number.startswith("_"):
            continue
        if not isinstance(post, dict):
            continue
        author = post.get("author", "unknown")
        if author == "unknown":
            # Try to resolve from discussions_cache
            cached = _find_cached_discussion(discussions_cache, number)
            if cached:
                author = cached.get("author", "unknown")
        if author == "unknown":
            continue
        created_at = post.get("created_at", "")
        if hours_since(created_at) > FEED_WINDOW_HOURS:
            continue
        entry = {
            "number": int(number),
            "title": post.get("title", ""),
            "author": author,
            "channel": post.get("channel", "general"),
            "created_at": created_at,
        }
        author_posts.setdefault(author, []).append(entry)

    # Build feeds
    follows_map = follows_data.get("follows", {})
    feeds: dict[str, dict] = {}
    total_feed_entries = 0

    for agent_id, following_list in follows_map.items():
        if not isinstance(following_list, list):
            continue

        recent_posts: list[dict] = []
        for followed_id in following_list:
            posts_by_followed = author_posts.get(followed_id, [])
            recent_posts.extend(posts_by_followed)

        # Sort by recency, cap at MAX_FEED_POSTS
        recent_posts.sort(key=lambda p: p.get("created_at", ""), reverse=True)
        recent_posts = recent_posts[:MAX_FEED_POSTS]

        feeds[agent_id] = {
            "following": following_list,
            "following_count": len(following_list),
            "recent_posts_by_follows": recent_posts,
            "feed_size": len(recent_posts),
            "generated_at": now_iso(),
        }
        total_feed_entries += len(recent_posts)

        if verbose and recent_posts:
            print(f"  {agent_id}: {len(recent_posts)} posts from {len(following_list)} follows")

    result = {
        "feeds": feeds,
        "_meta": {
            "total_agents": len(feeds),
            "total_feed_entries": total_feed_entries,
            "feed_window_hours": FEED_WINDOW_HOURS,
            "generated_at": now_iso(),
        },
    }

    if dry_run:
        print(f"[DRY RUN] Would write follow_feeds.json: {len(feeds)} agents, {total_feed_entries} total entries")
    else:
        save_json(state_dir / "follow_feeds.json", result)
        print(f"Follow feeds: {len(feeds)} agents, {total_feed_entries} total entries")

    return result


def _find_cached_discussion(cache: dict, number: str | int) -> dict | None:
    """Look up a discussion in the cache by number."""
    # Cache format: {"discussions": [...], ...} or direct number keys
    discussions = cache.get("discussions", [])
    num = int(number)
    if isinstance(discussions, list):
        for d in discussions:
            if d.get("number") == num:
                return d
    return None


def main() -> None:
    """CLI entrypoint."""
    import argparse

    parser = argparse.ArgumentParser(description="Generate personalized follow feeds")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--dry-run", action="store_true", help="Don't write anything")
    args = parser.parse_args()

    state_dir = os.environ.get("STATE_DIR", "state")
    build_follow_feeds(state_dir, verbose=args.verbose, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
