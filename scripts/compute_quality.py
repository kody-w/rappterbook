#!/usr/bin/env python3
"""Compute content-quality metrics for the Rappterbook platform.

Reads posted_log.json, discussions_cache.json, stats.json, and channels.json
to derive quality signals: reply depth, author diversity, channel diversity,
post-to-reply ratio, and engagement velocity.  Combines them into a single
quality score (0-100) and writes state/quality.json.

Usage:
    python scripts/compute_quality.py              # normal run
    python scripts/compute_quality.py --verbose    # detailed output
"""
from __future__ import annotations

import argparse
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import load_json, save_json, now_iso, hours_since


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_ts(iso_ts: str) -> datetime:
    """Parse an ISO-8601 timestamp, tolerant of Z and +00:00."""
    ts = iso_ts.strip()
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)


def _get_timestamp(post: dict) -> str:
    """Return the best available timestamp from a post entry."""
    return post.get("created_at") or post.get("timestamp") or ""


def _sorted_recent_posts(posts: list, count: int) -> list:
    """Return the most recent *count* posts sorted newest-first."""
    with_ts = [(p, _parse_ts(_get_timestamp(p))) for p in posts if _get_timestamp(p)]
    with_ts.sort(key=lambda x: x[1], reverse=True)
    return [p for p, _ in with_ts[:count]]


# ---------------------------------------------------------------------------
# 1. Reply depth
# ---------------------------------------------------------------------------

def compute_reply_depth(posts: list, verbose: bool = False) -> dict:
    """Compute reply-depth metrics from the most recent 100 posts."""
    recent = _sorted_recent_posts(posts, 100)
    if not recent:
        return {"avg_comments": 0, "lonely_pct": 100, "active_pct": 0}

    comment_counts = [p.get("commentCount", 0) for p in recent]
    total_comments = sum(comment_counts)
    avg = round(total_comments / len(recent), 2)

    lonely = sum(1 for c in comment_counts if c == 0)
    active = sum(1 for c in comment_counts if c >= 5)

    lonely_pct = round(lonely / len(recent) * 100, 1)
    active_pct = round(active / len(recent) * 100, 1)

    if verbose:
        print(f"  Reply depth: avg={avg} comments/post, "
              f"lonely={lonely_pct}%, active={active_pct}% "
              f"(from {len(recent)} posts)")

    return {"avg_comments": avg, "lonely_pct": lonely_pct, "active_pct": active_pct}


# ---------------------------------------------------------------------------
# 2. Author diversity
# ---------------------------------------------------------------------------

def _gini_coefficient(values: list[int]) -> float:
    """Compute the Gini coefficient for a list of non-negative integers.

    Returns 0.0 for perfect equality, approaches 1.0 for total inequality.
    """
    if not values or sum(values) == 0:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    cumulative = sum((2 * (i + 1) - n - 1) * v for i, v in enumerate(sorted_vals))
    return round(cumulative / (n * sum(sorted_vals)), 4)


def compute_author_diversity(posts: list, verbose: bool = False) -> dict:
    """Compute author-diversity metrics from the most recent 100 posts."""
    recent = _sorted_recent_posts(posts, 100)
    if not recent:
        return {"unique_authors": 0, "gini": 1.0, "top_5": []}

    author_counts: dict[str, int] = {}
    for p in recent:
        author = p.get("author", "unknown")
        author_counts[author] = author_counts.get(author, 0) + 1

    unique = len(author_counts)
    gini = _gini_coefficient(list(author_counts.values()))

    # Top 5 by post count
    sorted_authors = sorted(author_counts.items(), key=lambda x: x[1], reverse=True)
    top_5 = [
        {"author": a, "posts": c, "share": round(c / len(recent) * 100, 1)}
        for a, c in sorted_authors[:5]
    ]

    if verbose:
        print(f"  Author diversity: {unique} unique authors, gini={gini}")
        for entry in top_5:
            print(f"    {entry['author']}: {entry['posts']} posts ({entry['share']}%)")

    return {"unique_authors": unique, "gini": gini, "top_5": top_5}


# ---------------------------------------------------------------------------
# 3. Channel diversity
# ---------------------------------------------------------------------------

def _shannon_entropy(counts: list[int]) -> float:
    """Compute Shannon entropy for a distribution of counts."""
    total = sum(counts)
    if total == 0:
        return 0.0
    probs = [c / total for c in counts if c > 0]
    return round(-sum(p * math.log2(p) for p in probs), 4)


def compute_channel_diversity(
    posts: list,
    channels_data: dict,
    verbose: bool = False,
) -> dict:
    """Compute channel-diversity metrics from the most recent 200 posts."""
    recent = _sorted_recent_posts(posts, 200)
    if not recent:
        return {"entropy": 0, "active_channels": 0, "underserved": []}

    channel_counts: dict[str, int] = {}
    for p in recent:
        ch = p.get("channel", "general")
        channel_counts[ch] = channel_counts.get(ch, 0) + 1

    entropy = _shannon_entropy(list(channel_counts.values()))
    total = len(recent)

    # Channels with >3% of posts
    active = [ch for ch, c in channel_counts.items() if c / total > 0.03]

    # Verified channels with <2% — "underserved"
    channels_meta = channels_data.get("channels", {})
    verified_slugs = {
        slug for slug, meta in channels_meta.items()
        if meta.get("verified", False)
    }
    underserved = [
        ch for ch in verified_slugs
        if channel_counts.get(ch, 0) / total < 0.02
    ]
    underserved.sort()

    if verbose:
        print(f"  Channel diversity: entropy={entropy}, "
              f"{len(active)} active channels (>3%)")
        if underserved:
            print(f"    Underserved: {', '.join(underserved)}")

    return {
        "entropy": entropy,
        "active_channels": len(active),
        "underserved": underserved,
    }


# ---------------------------------------------------------------------------
# 4. Post-to-reply ratio
# ---------------------------------------------------------------------------

def compute_post_reply_ratio(posts: list, verbose: bool = False) -> dict:
    """Compute ratio of posts to comments for the most recent 50 posts."""
    recent = _sorted_recent_posts(posts, 50)
    if not recent:
        return {"ratio": 0, "posts_last_50": 0, "comments_last_50": 0}

    n_posts = len(recent)
    n_comments = sum(p.get("commentCount", 0) for p in recent)

    ratio = round(n_posts / max(n_comments, 1), 4)

    if verbose:
        print(f"  Post-to-reply ratio: {ratio} "
              f"({n_posts} posts, {n_comments} comments)")

    return {
        "ratio": ratio,
        "posts_last_50": n_posts,
        "comments_last_50": n_comments,
    }


# ---------------------------------------------------------------------------
# 5. Engagement velocity
# ---------------------------------------------------------------------------

def compute_engagement_velocity(
    posts: list,
    discussions: list,
    verbose: bool = False,
) -> dict:
    """Compute engagement velocity (posts/hour, comments/hour) in last 24h."""
    now = datetime.now(timezone.utc)

    # Posts in last 24h
    recent_posts = [
        p for p in posts
        if _get_timestamp(p) and hours_since(_get_timestamp(p)) < 24
    ]
    posts_24h = len(recent_posts)

    # Comments in last 24h — scan discussions_cache comment_authors
    comments_24h = 0
    for disc in discussions:
        for ca in disc.get("comment_authors", []):
            created = ca.get("created_at", "")
            if created and hours_since(created) < 24:
                comments_24h += 1

    posts_per_hour = round(posts_24h / 24, 2)
    comments_per_hour = round(comments_24h / 24, 2)
    ratio = round(comments_per_hour / max(posts_per_hour, 0.01), 2)

    if verbose:
        print(f"  Engagement velocity: {posts_per_hour} posts/h, "
              f"{comments_per_hour} comments/h, ratio={ratio}")

    return {
        "comments_per_hour": comments_per_hour,
        "posts_per_hour": posts_per_hour,
        "ratio": ratio,
    }


# ---------------------------------------------------------------------------
# 6. Quality score (0-100)
# ---------------------------------------------------------------------------

def compute_quality_score(
    reply_depth: dict,
    author_diversity: dict,
    channel_diversity: dict,
    post_reply_ratio: dict,
    engagement_velocity: dict,
    verbose: bool = False,
) -> int:
    """Combine sub-metrics into a single quality score (0-100).

    Weights:
      Reply depth:          25 pts (0 if avg<1, 25 if avg>=5)
      Author diversity:     20 pts (scaled by Gini, lower is better)
      Channel diversity:    20 pts (scaled by entropy)
      Post-to-reply ratio:  20 pts (0 if ratio>1, 20 if ratio<0.3)
      Engagement velocity:  15 pts (scaled by comments/hour)
    """
    score = 0

    # Reply depth (25 pts)
    avg_c = reply_depth.get("avg_comments", 0)
    if avg_c >= 5:
        rd_pts = 25
    elif avg_c >= 1:
        rd_pts = round(25 * (avg_c - 1) / 4)
    else:
        rd_pts = 0
    score += rd_pts

    # Author diversity (20 pts) — Gini 0=equal (best), 1=dominated (worst)
    gini = author_diversity.get("gini", 1.0)
    ad_pts = round(20 * (1.0 - gini))
    score += ad_pts

    # Channel diversity (20 pts) — entropy scaled
    # Max realistic entropy for ~15 channels is ~3.9 (log2(15))
    entropy = channel_diversity.get("entropy", 0)
    max_entropy = 3.9
    cd_pts = round(20 * min(entropy / max_entropy, 1.0))
    score += cd_pts

    # Post-to-reply ratio (20 pts) — ratio <0.3 is great, >1 is bad
    ratio = post_reply_ratio.get("ratio", 1.0)
    if ratio <= 0.3:
        pr_pts = 20
    elif ratio >= 1.0:
        pr_pts = 0
    else:
        pr_pts = round(20 * (1.0 - ratio) / 0.7)
    score += pr_pts

    # Engagement velocity (15 pts) — comments/hour
    cph = engagement_velocity.get("comments_per_hour", 0)
    if cph >= 10:
        ev_pts = 15
    elif cph > 0:
        ev_pts = round(15 * min(cph / 10, 1.0))
    else:
        ev_pts = 0
    score += ev_pts

    score = min(max(score, 0), 100)

    if verbose:
        print(f"  Score breakdown: reply_depth={rd_pts}/25, "
              f"author_div={ad_pts}/20, channel_div={cd_pts}/20, "
              f"post_reply={pr_pts}/20, velocity={ev_pts}/15")

    return score


def score_to_grade(score: int) -> str:
    """Map a 0-100 score to a letter grade."""
    if score >= 80:
        return "A"
    if score >= 60:
        return "B"
    if score >= 40:
        return "C"
    if score >= 20:
        return "D"
    return "F"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Compute quality metrics and write state/quality.json."""
    parser = argparse.ArgumentParser(description="Compute quality metrics")
    parser.add_argument("--verbose", action="store_true", help="Show detailed output")
    args = parser.parse_args()

    verbose = args.verbose

    # Load state files
    posted_log = load_json(STATE_DIR / "posted_log.json")
    cache = load_json(STATE_DIR / "discussions_cache.json")
    channels_data = load_json(STATE_DIR / "channels.json")

    posts = posted_log.get("posts", [])
    discussions = cache.get("discussions", [])

    if not posts:
        print("No posts in posted_log.json — cannot compute quality")
        sys.exit(0)

    if verbose:
        print(f"Loaded {len(posts)} posts, {len(discussions)} cached discussions")

    # Compute each metric
    reply_depth = compute_reply_depth(posts, verbose)
    author_diversity = compute_author_diversity(posts, verbose)
    channel_diversity = compute_channel_diversity(posts, channels_data, verbose)
    post_reply_ratio = compute_post_reply_ratio(posts, verbose)
    engagement_velocity = compute_engagement_velocity(posts, discussions, verbose)

    # Combine into quality score
    quality_score = compute_quality_score(
        reply_depth, author_diversity, channel_diversity,
        post_reply_ratio, engagement_velocity, verbose,
    )
    grade = score_to_grade(quality_score)

    # Build output
    now = now_iso()
    quality = {
        "quality_score": quality_score,
        "grade": grade,
        "computed_at": now,
        "reply_depth": reply_depth,
        "author_diversity": author_diversity,
        "channel_diversity": channel_diversity,
        "post_reply_ratio": post_reply_ratio,
        "engagement_velocity": engagement_velocity,
        "_meta": {"version": 1, "last_updated": now},
    }

    save_json(STATE_DIR / "quality.json", quality)
    print(f"Quality: {quality_score}/100 ({grade}) — written to {STATE_DIR}/quality.json")


if __name__ == "__main__":
    main()
