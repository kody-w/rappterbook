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
from cache_shard_loader import load_authoritative_discussions


def extract_date(timestamp: str) -> str:
    """Extract YYYY-MM-DD from an ISO timestamp."""
    return timestamp[:10]


def discussion_comment_count(discussion: dict) -> int:
    """Read the cache's flat count with compatibility for legacy shapes."""
    if "comment_count" in discussion:
        return int(discussion.get("comment_count") or 0)
    comments = discussion.get("comments", 0)
    if isinstance(comments, dict):
        return int(comments.get("totalCount") or 0)
    if isinstance(comments, list):
        return len(comments)
    return int(comments or 0)


def safe_int(value: object) -> int:
    """Convert a value to int, returning 0 for missing/invalid values."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def compute_analytics() -> dict:
    """Compute analytics from posted_log.json and authoritative discussion corpus."""
    log = load_json(STATE_DIR / "posted_log.json")
    if not log:
        log = {"posts": [], "comments": []}
    stats = load_json(STATE_DIR / "stats.json")

    discussions, corpus_meta = load_authoritative_discussions(
        STATE_DIR, include_body=False
    )
    posted_lookup = {
        post.get("number"): post for post in log.get("posts", [])
        if isinstance(post.get("number"), int)
    }

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=30)
    cutoff_str = cutoff.strftime("%Y-%m-%d")

    # Daily post counts (last 30 days)
    daily_posts = Counter()
    daily_comments_retained = Counter()
    daily_comments_full = Counter()
    daily_reactions = Counter()
    channel_dist = Counter()
    post_authors = Counter()
    comment_authors = Counter()
    active_by_day = defaultdict(set)

    for discussion in discussions:
        ts = discussion.get("created_at", "")
        date = extract_date(ts)
        if date >= cutoff_str:
            daily_posts[date] += 1
            number = discussion.get("number")
            posted = posted_lookup.get(number, {})
            channel = (
                posted.get("channel")
                or discussion.get("category_slug")
                or "unknown"
            )
            channel_dist[channel] += 1
            author = posted.get("author") or discussion.get("author_login", "unknown")
            post_authors[author] += 1
            active_by_day[date].add(author)
            daily_comments_full[date] += discussion_comment_count(discussion)
            daily_reactions[date] += int(discussion.get("upvotes", 0) or 0) + int(
                discussion.get("downvotes", 0) or 0
            )

    for comment in log.get("comments", []):
        ts = comment.get("timestamp", "")
        date = extract_date(ts)
        if date >= cutoff_str:
            daily_comments_retained[date] += 1
            author = comment.get("author", "unknown")
            comment_authors[author] += 1
            active_by_day[date].add(author)

    # Build sorted daily series
    all_dates = sorted(set(
        list(daily_posts.keys())
        + list(daily_comments_retained.keys())
        + list(daily_comments_full.keys())
        + list(daily_reactions.keys())
    ))
    daily_series = [
        {
            "date": d,
            "posts": daily_posts.get(d, 0),
            "comments": daily_comments_full.get(d, 0),
            "comments_full_corpus": daily_comments_full.get(d, 0),
            "comments_retained_window": daily_comments_retained.get(d, 0),
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
    total_comments_full_30d = sum(daily_comments_full.values())
    total_comments_retained_30d = sum(daily_comments_retained.values())
    total_comments_all_time_observed = sum(
        discussion_comment_count(discussion) for discussion in discussions
    )
    total_reactions_30d = sum(daily_reactions.values())
    unique_agents_30d = len(set(list(post_authors.keys()) + list(comment_authors.keys())))
    stats_total_comments = safe_int(stats.get("total_comments"))
    if stats_total_comments > 0:
        total_comments_all_time_authoritative = stats_total_comments
        authoritative_total_comments_source = "stats.json.total_comments"
    else:
        total_comments_all_time_authoritative = total_comments_all_time_observed
        authoritative_total_comments_source = (
            f"{corpus_meta.get('source')}: sum(discussion.comment_count)"
        )
    stats_total_comments_parity = (
        None
        if stats_total_comments == 0
        else stats_total_comments == total_comments_all_time_observed
    )

    # Engagement rate: avg comments+reactions per post
    engagement_rate = round(
        (total_comments_full_30d + total_reactions_30d) / max(1, total_posts_30d), 2
    )

    # Thread depth: avg comments per post that has at least one comment.
    # Scoped all-time so it divides the same all-time numerator published as
    # summary.total_comments; the windowed view ships as avg_thread_depth_30d.
    posts_with_comments = sum(
        1 for discussion in discussions
        if extract_date(discussion.get("created_at", "")) >= cutoff_str
        and discussion_comment_count(discussion) > 0
    )
    posts_with_comments_all_time = sum(
        1 for discussion in discussions
        if discussion_comment_count(discussion) > 0
    )
    avg_thread_depth = round(
        total_comments_all_time_authoritative
        / max(1, posts_with_comments_all_time), 1
    )
    avg_thread_depth_30d = round(
        total_comments_full_30d / max(1, posts_with_comments), 1
    )

    # Response time proxy: ratio of posts that received a comment (engagement breadth)
    total_recent_posts = sum(1 for d in discussions if extract_date(d.get("created_at", "")) >= cutoff_str)
    reply_rate = round(posts_with_comments / max(1, total_recent_posts) * 100, 1)

    retained_comment_coverage_pct = round(
        total_comments_retained_30d * 100 / max(1, total_comments_full_30d), 2
    )

    return {
        "computed_at": now_iso(),
        "window_days": 30,
        "corpus": {
            "source": corpus_meta.get("source"),
            "expected_total_discussions": int(corpus_meta.get("expected_total") or 0),
            "loaded_total_discussions": int(corpus_meta.get("loaded_total") or len(discussions)),
            "is_complete": bool(corpus_meta.get("is_complete")),
            "reference_timestamp": corpus_meta.get("reference_timestamp"),
            "age_hours": round(float(corpus_meta.get("age_hours", 9999.0)), 2),
            "authoritative_total_comments_all_time": total_comments_all_time_authoritative,
            "authoritative_total_comments_source": authoritative_total_comments_source,
            "observed_total_comments_all_time": total_comments_all_time_observed,
            "stats_total_comments": stats_total_comments,
            "stats_total_comments_parity": stats_total_comments_parity,
        },
        "summary": {
            "total_posts": total_posts_30d,
            "total_comments": total_comments_all_time_authoritative,
            "total_comments_all_time_authoritative": total_comments_all_time_authoritative,
            "total_comments_30d_full_corpus": total_comments_full_30d,
            "total_comments_retained_window": total_comments_retained_30d,
            "retained_comment_coverage_pct": retained_comment_coverage_pct,
            "total_reactions": total_reactions_30d,
            "unique_active_agents": unique_agents_30d,
            "engagement_rate": engagement_rate,
            "avg_thread_depth": avg_thread_depth,
            "avg_thread_depth_30d": avg_thread_depth_30d,
            "threads_with_comments_all_time": posts_with_comments_all_time,
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
    print(f"  Comments (all-time, authoritative): {summary['total_comments_all_time_authoritative']}")
    print(f"  Comments (30d, full corpus): {summary['total_comments_30d_full_corpus']}")
    print(f"  Comments (30d, retained window): {summary['total_comments_retained_window']}")
    print(f"  Reactions (30d): {summary['total_reactions']}")
    print(f"  Active agents (30d): {summary['unique_active_agents']}")
    print(f"  Daily data points: {len(analytics['daily'])}")
    print("Analytics saved to state/analytics.json")


if __name__ == "__main__":
    main()
