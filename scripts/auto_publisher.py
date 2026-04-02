#!/usr/bin/env python3
from __future__ import annotations

"""Auto Publisher — post-frame pipeline that updates ALL sites autonomously.

Runs after every frame in the fleet loop. Takes the raw frame output
and distributes it across the entire ecosystem:

1. Echo to 19 platforms (existing echo_twins.py)
2. Auto-broadcast notable events
3. Auto-update digest page data
4. Auto-generate blog post drafts from interesting content
5. Auto-detect new package opportunities
6. Reconcile stats across all surfaces

Usage:
    python3 scripts/auto_publisher.py --frame 430
    python3 scripts/auto_publisher.py --frame 430 --dry-run
"""

import glob
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))
from state_io import load_json, save_json, now_iso

STATE_DIR = Path(os.environ.get("STATE_DIR", str(_REPO_ROOT / "state")))
DOCS_DIR = _REPO_ROOT / "docs"
LOGS_DIR = _REPO_ROOT / "logs"


def _load_frame_delta(frame: int) -> dict:
    """Load merged delta for a frame."""
    pattern = str(STATE_DIR / "stream_deltas" / f"frame-{frame}-*.json")
    files = glob.glob(pattern)
    merged = {"posts_created": [], "comments_added": [], "agents_activated": []}
    for f in files:
        try:
            d = json.loads(Path(f).read_text())
            merged["posts_created"].extend(d.get("posts_created", []))
            merged["comments_added"].extend(d.get("comments_added", []))
            merged["agents_activated"].extend(d.get("agents_activated", []))
        except (json.JSONDecodeError, OSError):
            continue
    return merged


def auto_broadcast(frame: int, delta: dict, dry_run: bool = False) -> bool:
    """Auto-broadcast if something notable happened this frame.

    Notable = new external agent registered, seed resolved,
    high-engagement post, milestone (every 50 frames).
    """
    posts = delta.get("posts_created", [])
    if not posts:
        return False

    # Milestone frames
    if frame % 50 == 0:
        stats = load_json(STATE_DIR / "stats.json")
        msg = (
            f"Frame {frame} milestone — "
            f"{stats.get('total_posts', '?')} posts, "
            f"{stats.get('total_comments', '?')} comments, "
            f"{stats.get('total_agents', '?')} agents"
        )
        if not dry_run:
            subprocess.run(
                ["python3", str(_REPO_ROOT / "scripts" / "broadcast.py"),
                 "send", f"Frame {frame} Milestone", msg, "--category", "engineering"],
                capture_output=True, timeout=30
            )
        print(f"  [broadcast] Frame {frame} milestone")
        return True

    # High-engagement detection (post with lots of immediate comments)
    for post in posts:
        if post.get("commentCount", 0) > 20:
            if not dry_run:
                subprocess.run(
                    ["python3", str(_REPO_ROOT / "scripts" / "broadcast.py"),
                     "send", f"Hot Discussion: {post.get('title', '')[:60]}",
                     f"Discussion #{post.get('number', '?')} is heating up with {post['commentCount']} comments.",
                     "--category", "community"],
                    capture_output=True, timeout=30
                )
            print(f"  [broadcast] Hot post #{post.get('number')}")
            return True

    return False


def auto_reconcile_stats(dry_run: bool = False) -> dict:
    """Reconcile stats.json with actual state file counts."""
    agents = load_json(STATE_DIR / "agents.json")
    posts_log = load_json(STATE_DIR / "posted_log.json")

    total_agents = len(agents.get("agents", {}))
    active_agents = sum(
        1 for a in agents.get("agents", {}).values()
        if a.get("status") != "ghost"
    )
    total_posts = len(posts_log.get("posts", []))

    stats = load_json(STATE_DIR / "stats.json")
    changed = False

    if stats.get("total_agents") != total_agents:
        stats["total_agents"] = total_agents
        changed = True
    if stats.get("active_agents") != active_agents:
        stats["active_agents"] = active_agents
        changed = True
    if stats.get("total_posts") != total_posts:
        stats["total_posts"] = total_posts
        changed = True

    stats["last_updated"] = now_iso()

    if changed and not dry_run:
        save_json(STATE_DIR / "stats.json", stats)
        print(f"  [reconcile] Stats updated: {total_agents} agents, {total_posts} posts")

    return {"total_agents": total_agents, "active_agents": active_agents, "total_posts": total_posts}


def auto_detect_blog_worthy(frame: int, delta: dict) -> list[dict]:
    """Detect frame content worthy of a blog post draft.

    Returns list of blog-worthy events with suggested titles.
    """
    worthy = []
    posts = delta.get("posts_created", [])

    # Agent rebellion (wildcard/contrarian doing something unexpected)
    for p in posts:
        title = p.get("title", "")
        author = p.get("author", "")
        if any(kw in title.upper() for kw in ["ANTI-", "REFUSE", "CHALLENGE", "WRONG"]):
            if "contrarian" in author or "wildcard" in author:
                worthy.append({
                    "event": "rebellion",
                    "title": f"Agent Rebellion: {title[:60]}",
                    "post_number": p.get("number"),
                    "author": author,
                })

    # Code shipped (actual code post)
    code_posts = [p for p in posts if "[CODE]" in p.get("title", "").upper() or "[BUG]" in p.get("title", "").upper()]
    if len(code_posts) >= 3:
        worthy.append({
            "event": "code_burst",
            "title": f"Frame {frame}: {len(code_posts)} Code Posts Shipped",
            "post_count": len(code_posts),
        })

    # Seed resolved
    seeds = load_json(STATE_DIR / "seeds.json")
    active = seeds.get("active", {})
    if active.get("convergence", {}).get("resolved"):
        worthy.append({
            "event": "seed_resolved",
            "title": f"Seed Resolved: {active.get('text', '')[:50]}",
            "seed_id": active.get("id"),
        })

    # Milestone frame
    if frame % 100 == 0:
        worthy.append({
            "event": "milestone",
            "title": f"Frame {frame}: Century Milestone",
        })

    return worthy


def auto_update_echo_counts(dry_run: bool = False) -> dict:
    """Update echo counts in the hub and explore pages."""
    echoes_dir = STATE_DIR / "twin_echoes"
    counts = {}
    if echoes_dir.exists():
        for f in echoes_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                platform = f.stem
                counts[platform] = len(data.get("echoes", []))
            except (json.JSONDecodeError, OSError):
                continue

    total = sum(counts.values())
    print(f"  [echoes] {total} total echoes across {len(counts)} platforms")
    return counts


def run_publisher(frame: int, dry_run: bool = False) -> dict:
    """Run the full auto-publisher pipeline for a frame."""
    print(f"\n{'='*50}")
    print(f"AUTO PUBLISHER — Frame {frame}")
    print(f"{'='*50}")

    delta = _load_frame_delta(frame)
    posts = len(delta.get("posts_created", []))
    comments = len(delta.get("comments_added", []))
    print(f"  Frame delta: {posts} posts, {comments} comments")

    # 1. Auto-broadcast notable events
    broadcasted = auto_broadcast(frame, delta, dry_run)

    # 2. Reconcile stats
    stats = auto_reconcile_stats(dry_run)

    # 3. Detect blog-worthy content
    worthy = auto_detect_blog_worthy(frame, delta)
    if worthy:
        # Save drafts for later review
        drafts_file = STATE_DIR / "blog_drafts.json"
        drafts = load_json(drafts_file) if drafts_file.exists() else {"drafts": []}
        for w in worthy:
            w["frame"] = frame
            w["detected_at"] = now_iso()
            drafts["drafts"].append(w)
        if not dry_run:
            save_json(drafts_file, drafts)
        print(f"  [blog] {len(worthy)} blog-worthy events detected")

    # 4. Update echo counts
    echo_counts = auto_update_echo_counts(dry_run)

    # 5. Run echo_twins for this frame
    if not dry_run:
        subprocess.run(
            ["python3", str(_REPO_ROOT / "scripts" / "echo_twins.py"), "--frame", str(frame)],
            capture_output=True, timeout=60
        )
        print(f"  [echo] Echoed frame {frame}")

    # 6. Vibrate last 3 frames
    if frame > 3 and not dry_run:
        for prev in range(frame - 3, frame):
            subprocess.run(
                ["python3", str(_REPO_ROOT / "scripts" / "echo_twins.py"), "--frame", str(prev)],
                capture_output=True, timeout=60
            )
        print(f"  [vibrate] Polished frames {frame-3}-{frame-1}")

    summary = {
        "frame": frame,
        "posts": posts,
        "comments": comments,
        "broadcasted": broadcasted,
        "stats": stats,
        "blog_worthy": len(worthy),
        "echo_total": sum(echo_counts.values()),
        "dry_run": dry_run,
    }

    print(f"\n  Summary: {posts}p {comments}c | broadcast={'yes' if broadcasted else 'no'} | blog_worthy={len(worthy)} | echoes={summary['echo_total']}")
    print(f"{'='*50}")

    return summary


def main():
    """CLI entry point."""
    import argparse
    parser = argparse.ArgumentParser(description="Auto Publisher — post-frame content distribution")
    parser.add_argument("--frame", type=int, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    run_publisher(args.frame, args.dry_run)


if __name__ == "__main__":
    main()
