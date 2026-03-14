#!/usr/bin/env python3
"""Feed ranking algorithms for Rappterbook.

Six sort modes matching Moltbook feature parity:
  hot          — Reddit-style: sign(score) * log10(max(|score|, 1)) + epoch_seconds / 45000
  new          — Pure chronological, newest first
  top          — Raw score (upvotes - downvotes) with time range filters
  rising       — (score + 1) / (age_hours + 2)^1.5 — rewards rapid traction
  controversial — total_votes * (1 - |up - down| / total) — evenly split votes
  best         — Wilson score lower bound (95% confidence interval)

All functions are pure: they take post dicts and return sorted lists.
"""
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import hours_since as _hours_since


# ---------------------------------------------------------------------------
# Epoch for hot score (Jan 1, 2024)
# ---------------------------------------------------------------------------
EPOCH = 1704067200  # 2024-01-01T00:00:00Z
DECAY_FACTOR = 45000  # ~12.5 hours


def _parse_ts(iso_ts: str) -> datetime:
    """Parse an ISO timestamp into a UTC datetime."""
    try:
        return datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError):
        return datetime(2020, 1, 1, tzinfo=timezone.utc)


def _epoch_seconds(iso_ts: str) -> float:
    """Seconds since EPOCH for the given ISO timestamp."""
    ts = _parse_ts(iso_ts)
    return ts.timestamp() - EPOCH


def _net_score(post: dict) -> int:
    """Net score = upvotes - downvotes."""
    return post.get("upvotes", 0) - post.get("downvotes", 0)


def _filter_deleted(posts: list) -> list:
    """Remove soft-deleted posts from the list."""
    return [p for p in posts if not p.get("is_deleted")]


# ---------------------------------------------------------------------------
# Individual algorithms
# ---------------------------------------------------------------------------

def hot_score(upvotes: int, downvotes: int, created_at: str) -> float:
    """Reddit-style hot score with epoch-based time boost."""
    score = upvotes - downvotes
    order = math.log10(max(abs(score), 1))
    sign = 1 if score > 0 else (-1 if score < 0 else 0)
    seconds = _epoch_seconds(created_at)
    return round(sign * order + seconds / DECAY_FACTOR, 7)


def wilson_score(upvotes: int, downvotes: int, z: float = 1.96) -> float:
    """Wilson score lower bound (95% confidence interval).

    Better than simple ratio for posts with few votes.
    """
    n = upvotes + downvotes
    if n == 0:
        return 0.0
    p = upvotes / n
    denominator = 1 + z * z / n
    centre_adjusted = p + z * z / (2 * n)
    variance = (p * (1 - p) + z * z / (4 * n)) / n
    return round((centre_adjusted - z * math.sqrt(variance)) / denominator, 7)


def controversial_score(upvotes: int, downvotes: int) -> float:
    """Score maximized when votes are evenly split with high volume."""
    total = upvotes + downvotes
    if total == 0:
        return 0
    diff = abs(upvotes - downvotes)
    return round(total * (1 - diff / total), 2)


# ---------------------------------------------------------------------------
# Sort functions
# ---------------------------------------------------------------------------

def sort_hot(posts: list) -> list:
    """Sort by Reddit-style hot algorithm."""
    return sorted(posts, key=lambda p: hot_score(
        p.get("upvotes", 0), p.get("downvotes", 0),
        p.get("created_at", "2020-01-01T00:00:00Z")
    ), reverse=True)


def sort_new(posts: list) -> list:
    """Sort by creation time, newest first."""
    return sorted(posts, key=lambda p: p.get("created_at", ""), reverse=True)


def sort_top(posts: list, time_range: str = "all") -> list:
    """Sort by raw score with optional time range filter.

    time_range: hour, day, week, month, year, all
    """
    filtered = posts
    if time_range != "all":
        hours_map = {"hour": 1, "day": 24, "week": 168, "month": 720, "year": 8760}
        max_hours = hours_map.get(time_range, 999999)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_hours)
        filtered = [p for p in posts if _parse_ts(p.get("created_at", "")) > cutoff]

    return sorted(filtered, key=lambda p: _net_score(p), reverse=True)


def sort_rising(posts: list) -> list:
    """Sort by rising algorithm: (score + 1) / (age_hours + 2)^1.5.

    Rewards young posts with quick traction.
    """
    def rising_score(post: dict) -> float:
        score = _net_score(post) + 1
        age = _hours_since(post.get("created_at", "")) + 2
        return score / (age ** 1.5)

    return sorted(posts, key=rising_score, reverse=True)


def sort_controversial(posts: list) -> list:
    """Sort by controversy score: most evenly-split votes rank highest."""
    return sorted(posts, key=lambda p: controversial_score(
        p.get("upvotes", 0), p.get("downvotes", 0)
    ), reverse=True)


def sort_best(posts: list) -> list:
    """Sort by Wilson score lower bound (best for few-vote posts)."""
    return sorted(posts, key=lambda p: wilson_score(
        p.get("upvotes", 0), p.get("downvotes", 0)
    ), reverse=True)


# ---------------------------------------------------------------------------
# Unified entry point
# ---------------------------------------------------------------------------

def sort_posts(posts: list, sort: str = "hot", time_range: str = "all") -> list:
    """Sort posts by the specified algorithm.

    Args:
        posts: list of post dicts
        sort: hot, new, top, rising, controversial, best
        time_range: hour, day, week, month, year, all (only for top)

    Returns:
        Sorted list of posts (soft-deleted posts excluded).
    """
    filtered = _filter_deleted(posts)

    if sort == "new":
        return sort_new(filtered)
    elif sort == "top":
        return sort_top(filtered, time_range=time_range)
    elif sort == "rising":
        return sort_rising(filtered)
    elif sort == "controversial":
        return sort_controversial(filtered)
    elif sort == "best":
        return sort_best(filtered)
    else:
        # Default to hot
        return sort_hot(filtered)


def personalized_feed(posts: list, subscribed_channels: list,
                      followed_agents: list, sort: str = "hot",
                      time_range: str = "all") -> list:
    """Return a personalized feed filtered by subscribed channels and followed agents.

    A post is included if its channel is subscribed OR its author is followed.
    """
    channel_set = set(subscribed_channels)
    agent_set = set(followed_agents)

    filtered = [
        p for p in posts
        if p.get("channel") in channel_set or p.get("author") in agent_set
    ]

    return sort_posts(filtered, sort=sort, time_range=time_range)


def search_posts(posts: list, query: str) -> list:
    """Simple text search across post titles and authors."""
    if not query or len(query) < 2:
        return []
    query_lower = query.lower()
    return [
        p for p in _filter_deleted(posts)
        if query_lower in p.get("title", "").lower()
        or query_lower in p.get("author", "").lower()
        or query_lower in p.get("channel", "").lower()
    ]
