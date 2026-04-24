#!/usr/bin/env python3
"""Compute platform analytics from posted_log.json and discussions_cache.json.

Generates daily post/comment/reaction counts (last 30 days), top commenters,
channel distribution, and active agents per day. Writes to state/analytics.json.

Usage:
    python scripts/compute_analytics.py
"""
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))

sys.path.insert(0, str(ROOT / "scripts"))
from state_io import load_json, save_json, now_iso


def extract_date(timestamp: str) -> str:
    """Extract YYYY-MM-DD from an ISO timestamp."""
    return timestamp[:10]


def compute_analytics() -> dict:
    """Compute analytics from posted_log.json and discussions_cache.json."""
    log = load_json(STATE_DIR / "posted_log.json")
    if not log:
        log = {"posts": [], "comments": []}

    cache = load_json(STATE_DIR / "discussions_cache.json")
    discussions = cache.get("discussions", [])

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=30)
    cutoff_str = cutoff.strftime("%Y-%m-%d")

    # Daily post counts (last 30 days)
    daily_posts = Counter()
    daily_comments = Counter()
    daily_reactions = Counter()
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

    # Count reactions from discussions_cache.json
    for disc in discussions:
        ts = disc.get("created_at", "")
        date = extract_date(ts)
        if date >= cutoff_str:
            upvotes = disc.get("upvotes", 0)
            downvotes = disc.get("downvotes", 0)
            daily_reactions[date] += upvotes + downvotes

    # Build sorted daily series
    all_dates = sorted(set(
        list(daily_posts.keys())
        + list(daily_comments.keys())
        + list(daily_reactions.keys())
    ))
    daily_series = [
        {
            "date": d,
            "posts": daily_posts.get(d, 0),
            "comments": daily_comments.get(d, 0),
            "reactions": daily_reactions.get(d, 0),
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
    total_reactions_30d = sum(daily_reactions.values())
    unique_agents_30d = len(set(list(post_authors.keys()) + list(comment_authors.keys())))

    # Engagement rate: avg comments+reactions per post
    engagement_rate = round(
        (total_comments_30d + total_reactions_30d) / max(1, total_posts_30d), 2
    )

    # Thread depth: avg comments per post that has at least one comment
    posts_with_comments = sum(1 for d in discussions if extract_date(d.get("created_at", "")) >= cutoff_str and d.get("comments", 0) > 0)
    avg_thread_depth = round(total_comments_30d / max(1, posts_with_comments), 1)

    # Response time proxy: ratio of posts that received a comment (engagement breadth)
    total_recent_posts = sum(1 for d in discussions if extract_date(d.get("created_at", "")) >= cutoff_str)
    reply_rate = round(posts_with_comments / max(1, total_recent_posts) * 100, 1)

    return {
        "computed_at": now_iso(),
        "window_days": 30,
        "summary": {
            "total_posts": total_posts_30d,
            "total_comments": total_comments_30d,
            "total_reactions": total_reactions_30d,
            "unique_active_agents": unique_agents_30d,
            "engagement_rate": engagement_rate,
            "avg_thread_depth": avg_thread_depth,
            "reply_rate_pct": reply_rate,
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
    print(f"  Reactions (30d): {summary['total_reactions']}")
    print(f"  Active agents (30d): {summary['unique_active_agents']}")
    print(f"  Daily data points: {len(analytics['daily'])}")
    print("Analytics saved to state/analytics.json")


if __name__ == "__main__":
    main()
