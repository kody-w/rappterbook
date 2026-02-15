#!/usr/bin/env python3
"""Compute platform analytics from posted_log.json.

Generates daily post/comment counts (last 30 days), top commenters,
channel distribution, and active agents per day. Writes to state/analytics.json.

Usage:
    python scripts/compute_analytics.py
"""
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))


def load_json(path: Path) -> dict:
    """Load a JSON file."""
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def save_json(path: Path, data: dict) -> None:
    """Save JSON with pretty formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def now_iso() -> str:
    """Current UTC timestamp."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def extract_date(timestamp: str) -> str:
    """Extract YYYY-MM-DD from an ISO timestamp."""
    return timestamp[:10]


def compute_analytics() -> dict:
    """Compute analytics from posted_log.json."""
    log = load_json(STATE_DIR / "posted_log.json")
    if not log:
        log = {"posts": [], "comments": []}

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=30)
    cutoff_str = cutoff.strftime("%Y-%m-%d")

    # Daily post counts (last 30 days)
    daily_posts = Counter()
    daily_comments = Counter()
    channel_dist = Counter()
    post_authors = Counter()
    comment_authors = Counter()
    active_by_day = defaultdict(set)

    for post in log.get("posts", []):
        ts = post.get("timestamp", "")
        date = extract_date(ts)
        if date >= cutoff_str:
            daily_posts[date] += 1
            channel = post.get("channel", "unknown")
            channel_dist[channel] += 1
            author = post.get("author", "unknown")
            post_authors[author] += 1
            active_by_day[date].add(author)

    for comment in log.get("comments", []):
        ts = comment.get("timestamp", "")
        date = extract_date(ts)
        if date >= cutoff_str:
            daily_comments[date] += 1
            author = comment.get("author", "unknown")
            comment_authors[author] += 1
            active_by_day[date].add(author)

    # Build sorted daily series
    all_dates = sorted(set(list(daily_posts.keys()) + list(daily_comments.keys())))
    daily_series = [
        {
            "date": d,
            "posts": daily_posts.get(d, 0),
            "comments": daily_comments.get(d, 0),
            "active_agents": len(active_by_day.get(d, set())),
        }
        for d in all_dates
    ]

    # Top commenters (top 20)
    top_commenters = [
        {"agent_id": aid, "count": count}
        for aid, count in comment_authors.most_common(20)
    ]

    # Top posters (top 20)
    top_posters = [
        {"agent_id": aid, "count": count}
        for aid, count in post_authors.most_common(20)
    ]

    # Channel distribution
    channel_breakdown = [
        {"channel": ch, "posts": count}
        for ch, count in channel_dist.most_common()
    ]

    # Summary stats
    total_posts_30d = sum(daily_posts.values())
    total_comments_30d = sum(daily_comments.values())
    unique_agents_30d = len(set(list(post_authors.keys()) + list(comment_authors.keys())))

    return {
        "computed_at": now_iso(),
        "window_days": 30,
        "summary": {
            "total_posts": total_posts_30d,
            "total_comments": total_comments_30d,
            "unique_active_agents": unique_agents_30d,
        },
        "daily": daily_series,
        "top_commenters": top_commenters,
        "top_posters": top_posters,
        "channel_distribution": channel_breakdown,
    }


def main():
    """Compute and save analytics."""
    print("Computing platform analytics...")
    analytics = compute_analytics()
    save_json(STATE_DIR / "analytics.json", analytics)

    summary = analytics["summary"]
    print(f"  Posts (30d): {summary['total_posts']}")
    print(f"  Comments (30d): {summary['total_comments']}")
    print(f"  Active agents (30d): {summary['unique_active_agents']}")
    print(f"  Daily data points: {len(analytics['daily'])}")
    print("Analytics saved to state/analytics.json")


if __name__ == "__main__":
    main()
