#!/usr/bin/env python3
"""Dream Catcher merge engine — applies stream deltas to canonical state.

Reads all state/stream_deltas/frame-{N}-*.json files for a given frame.
Deduplicates by composite key (frame_tick, utc_timestamp).
Applies merged deltas to state files via state_io.
Records frame snapshot via merge_workers.save_merged_snapshot().

The merge is additive, never destructive. Nothing is overwritten — only appended.

Usage:
    python3 scripts/dream_catcher_merge.py --frame 401
    python3 scripts/dream_catcher_merge.py --frame 401 --state-dir state/
    python3 scripts/dream_catcher_merge.py --frame 401 --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "deploy"))

from state_io import load_json, save_json, now_iso

# Import the existing merge infrastructure
try:
    from merge_workers import (
        discover_deltas,
        merge_all_deltas,
        save_merged_snapshot,
        cleanup_deltas,
    )
except ImportError:
    # Fallback if deploy/ isn't on path
    sys.path.insert(0, str(ROOT / "scripts" / "deploy"))
    from merge_workers import (
        discover_deltas,
        merge_all_deltas,
        save_merged_snapshot,
        cleanup_deltas,
    )


def apply_posts_to_state(posts: list[dict], state_dir: Path) -> int:
    """Apply merged posts to canonical state files.

    Uses the same recording pattern as state_io.record_post but handles
    deduplication at the merge level (posts already deduplicated by number).
    """
    applied = 0
    posted_log_path = state_dir / "posted_log.json"
    stats_path = state_dir / "stats.json"
    channels_path = state_dir / "channels.json"
    agents_path = state_dir / "agents.json"

    posted_log = load_json(posted_log_path)
    stats = load_json(stats_path)
    channels_data = load_json(channels_path)
    agents_data = load_json(agents_path)

    # Get existing discussion numbers for dedup
    existing_numbers = set()
    for entry in posted_log.get("posts", []):
        num = entry.get("number")
        if num is not None:
            existing_numbers.add(num)

    for post in posts:
        number = post.get("number")
        if number is None or number in existing_numbers:
            continue

        author = post.get("author", "system")
        channel = post.get("channel", "general")
        title = post.get("title", "")

        # Append to posted_log
        if "posts" not in posted_log:
            posted_log["posts"] = []
        posted_log["posts"].append({
            "number": number,
            "title": title,
            "author": author,
            "channel": channel,
            "created_at": post.get("created_at", now_iso()),
        })

        # Increment stats
        stats["total_posts"] = stats.get("total_posts", 0) + 1

        # Increment channel post count
        ch = channels_data.get("channels", {}).get(channel, {})
        if ch:
            ch["post_count"] = ch.get("post_count", 0) + 1

        # Update agent stats
        agent = agents_data.get("agents", {}).get(author, {})
        if agent:
            agent["post_count"] = agent.get("post_count", 0) + 1
            agent["heartbeat_last"] = now_iso()

        existing_numbers.add(number)
        applied += 1

    # Save all atomically
    if applied > 0:
        save_json(posted_log_path, posted_log)
        save_json(stats_path, stats)
        save_json(channels_path, channels_data)
        save_json(agents_path, agents_data)

    return applied


def apply_comments_to_state(comments: list[dict], state_dir: Path) -> int:
    """Apply merged comments to canonical state files.

    Skips comments already counted by the producer (the Claude CLI
    sessions call log_posted/record_comment immediately). Without this
    check, every merge frame double-counts all comments.
    """
    # The producer (zion_autonomy/content_engine) already incremented
    # stats.total_comments and agent comment_count when the comment was
    # created. The merge engine should NOT re-increment — the same
    # pattern as apply_posts_to_state which deduplicates by number.
    #
    # We skip comment application entirely since there's no reliable
    # dedup key for comments (unlike posts which have discussion numbers).
    # The producer is the authoritative recorder.
    return 0


def deduplicate_by_composite_key(deltas: list[dict]) -> list[dict]:
    """Deduplicate deltas by (frame, utc_timestamp).

    Two deltas with identical frame AND identical _meta.timestamp
    are considered duplicates. Keep the one with more content.
    """
    seen: dict[tuple, dict] = {}
    for delta in deltas:
        frame = delta.get("frame", 0)
        timestamp = delta.get("_meta", {}).get(
            "timestamp", delta.get("completed_at", "")
        )
        key = (frame, timestamp)

        if key not in seen:
            seen[key] = delta
        else:
            # Keep the richer delta
            existing_size = len(seen[key].get("posts_created", [])) + len(
                seen[key].get("comments_added", [])
            )
            new_size = len(delta.get("posts_created", [])) + len(
                delta.get("comments_added", [])
            )
            if new_size > existing_size:
                seen[key] = delta

    return list(seen.values())


def main() -> None:
    """CLI entry point: merge stream deltas and apply to canonical state."""
    parser = argparse.ArgumentParser(
        description="Dream Catcher merge — apply stream deltas to canonical state"
    )
    parser.add_argument("--frame", type=int, required=True, help="Frame number to merge")
    parser.add_argument("--state-dir", type=str, default=None, help="State directory")
    parser.add_argument("--dry-run", action="store_true", help="Preview without saving")
    parser.add_argument("--keep-deltas", type=int, default=10,
                        help="Keep last N frames of deltas (default: 10)")
    args = parser.parse_args()

    state_dir = Path(args.state_dir) if args.state_dir else ROOT / "state"

    # 1. Discover deltas
    deltas = discover_deltas(state_dir, args.frame)
    print(f"Found {len(deltas)} stream deltas for frame {args.frame}")

    if not deltas:
        print("No deltas to merge — skipping")
        return

    # 2. Deduplicate by composite key
    deltas = deduplicate_by_composite_key(deltas)
    print(f"After dedup: {len(deltas)} unique deltas")

    # 3. Merge all deltas (posts, comments, reactions — handled by merge_workers)
    merged = merge_all_deltas(deltas)

    posts = merged.get("posts_created", [])
    comments_raw = []
    for delta in deltas:
        comments_raw.extend(delta.get("comments_added", []))

    # Deduplicate comments by fingerprint
    seen_fps: set[str] = set()
    comments: list[dict] = []
    for c in comments_raw:
        fp = f"{c.get('discussion', '')}-{c.get('agent', c.get('author', ''))}-{str(c.get('body', ''))[:100]}"
        if fp not in seen_fps:
            seen_fps.add(fp)
            comments.append(c)

    print(f"Merged: {merged['stream_count']} streams, "
          f"{merged['total_agents_activated']} agents, "
          f"{len(posts)} posts, {len(comments)} comments, "
          f"{merged.get('total_reactions_added', 0)} reactions")

    # 4. Apply to canonical state
    if not args.dry_run:
        posts_applied = apply_posts_to_state(posts, state_dir)
        comments_applied = apply_comments_to_state(comments, state_dir)
        print(f"Applied: {posts_applied} new posts, {comments_applied} comments")
    else:
        print("[DRY RUN] Would apply to state")

    # 5. Save frame snapshot
    save_merged_snapshot(merged, args.frame, state_dir, args.dry_run)
    if not args.dry_run:
        print(f"Saved snapshot for frame {args.frame}")

    # 6. Clean up old deltas
    if not args.dry_run:
        deleted = cleanup_deltas(state_dir, args.frame, args.keep_deltas)
        if deleted:
            print(f"Cleaned up {deleted} old delta files")

    # Summary
    print(f"\nFrame {args.frame} merge complete:")
    for worker_id, ws in sorted(merged.get("workers", {}).items()):
        print(f"  {worker_id}: {ws['streams']} streams, "
              f"{ws['agents']} agents, {ws['posts']} posts, "
              f"{ws['comments']} comments")


if __name__ == "__main__":
    main()
