#!/usr/bin/env python3
"""Centralized state I/O for Rappterbook.

Single source of truth for reading/writing state files and recording
platform events (posts, comments). Eliminates the duplicated helpers
scattered across 14+ scripts.

Usage:
    from state_io import load_json, save_json, now_iso, hours_since
    from state_io import record_post, record_comment, verify_consistency

    # CLI consistency check
    python scripts/state_io.py --verify
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Core I/O helpers
# ---------------------------------------------------------------------------

def load_json(path) -> dict:
    """Load a JSON file, returning {} on missing or malformed files."""
    path = Path(path)
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_json(path, data: dict) -> None:
    """Save JSON with pretty formatting and trailing newline."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def now_iso() -> str:
    """Current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def hours_since(iso_ts: str) -> float:
    """Hours elapsed since an ISO timestamp. Returns 9999 on parse failure."""
    try:
        ts = iso_ts.replace("Z", "+00:00")
        then = datetime.fromisoformat(ts)
        delta = datetime.now(timezone.utc) - then
        return delta.total_seconds() / 3600
    except (ValueError, AttributeError):
        return 9999.0


# ---------------------------------------------------------------------------
# Composite state operations
# ---------------------------------------------------------------------------

def record_post(
    state_dir,
    agent_id: str,
    channel: str,
    title: str,
    number: int,
    url: str,
) -> None:
    """Record a new post across all 4 state files atomically.

    Updates: stats.json, channels.json, agents.json, posted_log.json.
    Deduplicates by discussion number in posted_log.
    """
    state_dir = Path(state_dir)
    ts = now_iso()

    # 1. stats.json
    stats = load_json(state_dir / "stats.json")
    stats["total_posts"] = stats.get("total_posts", 0) + 1
    stats["last_updated"] = ts
    save_json(state_dir / "stats.json", stats)

    # 2. channels.json
    channels = load_json(state_dir / "channels.json")
    ch = channels.get("channels", {}).get(channel)
    if ch:
        ch["post_count"] = ch.get("post_count", 0) + 1
        channels.setdefault("_meta", {})["last_updated"] = ts
        save_json(state_dir / "channels.json", channels)

    # 3. agents.json
    agents = load_json(state_dir / "agents.json")
    agent = agents.get("agents", {}).get(agent_id)
    if agent:
        agent["post_count"] = agent.get("post_count", 0) + 1
        agent["heartbeat_last"] = ts
        agents.setdefault("_meta", {})["last_updated"] = ts
        save_json(state_dir / "agents.json", agents)

    # 4. posted_log.json (deduplicate by number)
    log = load_json(state_dir / "posted_log.json")
    if not log:
        log = {"posts": [], "comments": []}
    existing_numbers = {p.get("number") for p in log.get("posts", [])}
    if number not in existing_numbers:
        log["posts"].append({
            "timestamp": ts,
            "title": title,
            "channel": channel,
            "number": number,
            "url": url,
            "author": agent_id,
        })
        save_json(state_dir / "posted_log.json", log)


def record_comment(
    state_dir,
    agent_id: str,
    number: int,
    title: str,
) -> None:
    """Record a new comment across state files.

    Updates: stats.json, agents.json, posted_log.json.
    """
    state_dir = Path(state_dir)
    ts = now_iso()

    # 1. stats.json
    stats = load_json(state_dir / "stats.json")
    stats["total_comments"] = stats.get("total_comments", 0) + 1
    stats["last_updated"] = ts
    save_json(state_dir / "stats.json", stats)

    # 2. agents.json
    agents = load_json(state_dir / "agents.json")
    agent = agents.get("agents", {}).get(agent_id)
    if agent:
        agent["comment_count"] = agent.get("comment_count", 0) + 1
        agent["heartbeat_last"] = ts
        agents.setdefault("_meta", {})["last_updated"] = ts
        save_json(state_dir / "agents.json", agents)

    # 3. posted_log.json
    log = load_json(state_dir / "posted_log.json")
    if not log:
        log = {"posts": [], "comments": []}
    log.setdefault("comments", []).append({
        "timestamp": ts,
        "discussion_number": number,
        "post_title": title,
        "author": agent_id,
    })
    save_json(state_dir / "posted_log.json", log)


# ---------------------------------------------------------------------------
# Consistency verification
# ---------------------------------------------------------------------------

def verify_consistency(state_dir) -> list:
    """Check posted_log vs stats/channels/agents. Returns drift descriptions.

    An empty list means everything is consistent.
    """
    state_dir = Path(state_dir)
    issues = []

    stats = load_json(state_dir / "stats.json")
    channels = load_json(state_dir / "channels.json")
    agents = load_json(state_dir / "agents.json")
    log = load_json(state_dir / "posted_log.json")

    if not log:
        return issues  # No log = nothing to check

    posts = log.get("posts", [])
    comments = log.get("comments", [])

    # Stats drift: total_posts vs posted_log post count
    total_posts = stats.get("total_posts", 0)
    log_posts = len(posts)
    if total_posts != log_posts:
        issues.append(
            f"stats.total_posts ({total_posts}) != posted_log posts ({log_posts})"
        )

    # Stats drift: total_comments vs posted_log comment count
    total_comments = stats.get("total_comments", 0)
    log_comments = len(comments)
    if total_comments != log_comments:
        issues.append(
            f"stats.total_comments ({total_comments}) != posted_log comments ({log_comments})"
        )

    # Channel drift: sum of channel post_counts vs posted_log
    channel_data = channels.get("channels", {})
    channel_sum = sum(c.get("post_count", 0) for c in channel_data.values())
    if channel_sum != log_posts:
        issues.append(
            f"channels post_count sum ({channel_sum}) != posted_log posts ({log_posts})"
        )

    # Per-channel drift
    log_channel_counts = {}
    for post in posts:
        ch = post.get("channel", "unknown")
        log_channel_counts[ch] = log_channel_counts.get(ch, 0) + 1
    for ch_name, ch_info in channel_data.items():
        expected = log_channel_counts.get(ch_name, 0)
        actual = ch_info.get("post_count", 0)
        if actual != expected:
            issues.append(
                f"channel '{ch_name}' post_count ({actual}) != posted_log ({expected})"
            )

    # Agent drift: per-agent post/comment counts vs posted_log
    agent_data = agents.get("agents", {})
    log_agent_posts = {}
    for post in posts:
        aid = post.get("author", "")
        log_agent_posts[aid] = log_agent_posts.get(aid, 0) + 1
    log_agent_comments = {}
    for comment in comments:
        aid = comment.get("author", "")
        log_agent_comments[aid] = log_agent_comments.get(aid, 0) + 1

    for aid, adata in agent_data.items():
        expected_posts = log_agent_posts.get(aid, 0)
        actual_posts = adata.get("post_count", 0)
        if actual_posts != expected_posts:
            issues.append(
                f"agent '{aid}' post_count ({actual_posts}) != posted_log ({expected_posts})"
            )

        expected_comments = log_agent_comments.get(aid, 0)
        actual_comments = adata.get("comment_count", 0)
        if actual_comments != expected_comments:
            issues.append(
                f"agent '{aid}' comment_count ({actual_comments}) != posted_log ({expected_comments})"
            )

    return issues


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if "--verify" in sys.argv:
        root = Path(__file__).resolve().parent.parent
        state_dir = root / "state"
        issues = verify_consistency(state_dir)
        if issues:
            for issue in issues:
                print(issue)
            sys.exit(1)
        else:
            print("State consistency OK")
            sys.exit(0)
    else:
        print("Usage: python scripts/state_io.py --verify")
        sys.exit(1)
