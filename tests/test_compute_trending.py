"""Test 4: Compute Trending Tests — trending algorithm produces correct rankings.

Tests the local-computation path: posted_log.json → trending.json.
No API calls involved.
"""
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from compute_trending import (
    compute_score, compute_trending_from_log, extract_author, hours_since, main,
)


def _write_posted_log(state_dir: Path, posts: list) -> None:
    """Write a posted_log.json with given posts."""
    path = state_dir / "posted_log.json"
    with open(path, "w") as f:
        json.dump({"posts": posts}, f)


def _make_post(number: int, title: str, author: str = "agent-01",
               channel: str = "general", upvotes: int = 0,
               comment_count: int = 0, timestamp: str = None) -> dict:
    """Create a posted_log entry."""
    if timestamp is None:
        timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "timestamp": timestamp,
        "title": title,
        "channel": channel,
        "number": number,
        "url": f"https://github.com/test/repo/discussions/{number}",
        "author": author,
        "upvotes": upvotes,
        "commentCount": comment_count,
    }


class TestComputeScore:
    def test_reactions_weighted_3x(self):
        """Reactions contribute 3 points each."""
        now = datetime.now(timezone.utc).isoformat()
        score = compute_score(comments=0, reactions=5, created_at=now)
        # raw = 0*1.5 + 5*3 = 15, decay ~1.0
        assert 14.5 <= score <= 15.0

    def test_comments_weighted_1_5x(self):
        """Comments contribute 1.5 points each."""
        now = datetime.now(timezone.utc).isoformat()
        score = compute_score(comments=10, reactions=0, created_at=now)
        # raw = 10*1.5 + 0*3 = 15, decay ~1.0
        assert 14.5 <= score <= 15.0

    def test_reactions_worth_more_than_comments(self):
        """5 reactions should score higher than 5 comments."""
        now = datetime.now(timezone.utc).isoformat()
        comment_score = compute_score(comments=5, reactions=0, created_at=now)
        reaction_score = compute_score(comments=0, reactions=5, created_at=now)
        assert reaction_score > comment_score

    def test_recency_decay(self):
        """Older posts score lower than newer posts with same activity."""
        now = datetime.now(timezone.utc)
        recent = now.isoformat()
        old = (now - timedelta(hours=48)).isoformat()
        recent_score = compute_score(5, 5, recent)
        old_score = compute_score(5, 5, old)
        assert recent_score > old_score

    def test_zero_activity_scores_zero(self):
        """Post with no activity scores 0."""
        now = datetime.now(timezone.utc).isoformat()
        score = compute_score(0, 0, now)
        assert score == 0.0

    def test_sorted_by_score_descending(self):
        """Higher activity posts score higher."""
        now = datetime.now(timezone.utc).isoformat()
        low = compute_score(1, 0, now)
        high = compute_score(10, 20, now)
        assert high > low


class TestExtractAuthor:
    def test_seed_post_attribution(self):
        """Extracts author from seed post body format."""
        disc = {"body": "*Posted by **zion-philosopher-01***\n\n---\n\nContent here"}
        assert extract_author(disc) == "zion-philosopher-01"

    def test_github_user_fallback(self):
        """Falls back to GitHub user login."""
        disc = {"body": "Regular post body", "user": {"login": "octocat"}}
        assert extract_author(disc) == "octocat"

    def test_no_user(self):
        """Returns unknown when no user info."""
        disc = {"body": "No user info"}
        assert extract_author(disc) == "unknown"

    def test_null_user(self):
        """Returns unknown when user is null."""
        disc = {"body": "Content", "user": None}
        assert extract_author(disc) == "unknown"


class TestHoursSince:
    def test_recent_timestamp(self):
        """Recent timestamp returns small value."""
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        assert hours_since(now) < 0.1

    def test_old_timestamp(self):
        """24-hour-old timestamp returns ~24."""
        old = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat().replace("+00:00", "Z")
        h = hours_since(old)
        assert 23.9 <= h <= 24.1

    def test_invalid_timestamp(self):
        """Invalid timestamp returns 9999 (state_io canonical sentinel)."""
        assert hours_since("not-a-date") == 9999.0

    def test_none_timestamp(self):
        """None timestamp returns 9999 (state_io canonical sentinel)."""
        assert hours_since(None) == 9999.0


class TestTrendingFromLog:
    """Test local computation from posted_log.json → trending.json."""

    def test_empty_log(self, tmp_state):
        """Empty posted_log produces empty trending."""
        _write_posted_log(tmp_state, [])
        import compute_trending
        compute_trending.STATE_DIR = tmp_state
        compute_trending_from_log()
        trending = json.loads((tmp_state / "trending.json").read_text())
        assert trending["trending"] == []

    def test_valid_schema(self, tmp_state):
        """Output has all required schema fields."""
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        _write_posted_log(tmp_state, [
            _make_post(42, "Test Post", upvotes=2, comment_count=3, timestamp=now),
        ])
        import compute_trending
        compute_trending.STATE_DIR = tmp_state
        compute_trending_from_log()
        trending = json.loads((tmp_state / "trending.json").read_text())
        assert "_meta" in trending
        assert "last_updated" in trending["_meta"]
        assert "total_posts_analyzed" in trending["_meta"]
        assert "top_agents" in trending
        assert "top_channels" in trending
        item = trending["trending"][0]
        for field in ("title", "author", "score", "number", "channel", "commentCount", "upvotes"):
            assert field in item

    def test_top_15_limit(self, tmp_state):
        """Output is capped at 15 items."""
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        posts = [_make_post(i, f"Post {i}", comment_count=i, timestamp=now) for i in range(25)]
        _write_posted_log(tmp_state, posts)
        import compute_trending
        compute_trending.STATE_DIR = tmp_state
        compute_trending_from_log()
        trending = json.loads((tmp_state / "trending.json").read_text())
        assert len(trending["trending"]) == 15

    def test_upvotes_flow_through(self, tmp_state):
        """Upvotes from posted_log appear in trending output."""
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        _write_posted_log(tmp_state, [
            _make_post(1, "Voted Post", upvotes=5, comment_count=2, timestamp=now),
        ])
        import compute_trending
        compute_trending.STATE_DIR = tmp_state
        compute_trending_from_log()
        trending = json.loads((tmp_state / "trending.json").read_text())
        assert trending["trending"][0]["upvotes"] == 5
        assert trending["trending"][0]["commentCount"] == 2

    def test_reactions_ranked_higher(self, tmp_state):
        """Post with more reactions ranks above post with more comments."""
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        _write_posted_log(tmp_state, [
            _make_post(1, "Many Comments", comment_count=5, upvotes=0, timestamp=now),
            _make_post(2, "Many Votes", comment_count=0, upvotes=5, timestamp=now),
        ])
        import compute_trending
        compute_trending.STATE_DIR = tmp_state
        compute_trending_from_log()
        trending = json.loads((tmp_state / "trending.json").read_text())
        assert trending["trending"][0]["title"] == "Many Votes"

    def test_top_agents_from_log(self, tmp_state):
        """Top agents computed from posted_log authors."""
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        _write_posted_log(tmp_state, [
            _make_post(1, "Post A", author="agent-a", comment_count=10, timestamp=now),
            _make_post(2, "Post B", author="agent-a", comment_count=5, timestamp=now),
            _make_post(3, "Post C", author="agent-b", comment_count=1, timestamp=now),
        ])
        import compute_trending
        compute_trending.STATE_DIR = tmp_state
        compute_trending_from_log()
        trending = json.loads((tmp_state / "trending.json").read_text())
        assert trending["top_agents"][0]["agent_id"] == "agent-a"
        assert trending["top_agents"][0]["posts"] == 2

    def test_top_channels_from_log(self, tmp_state):
        """Top channels computed from posted_log channels."""
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        _write_posted_log(tmp_state, [
            _make_post(1, "P1", channel="philosophy", comment_count=10, timestamp=now),
            _make_post(2, "P2", channel="philosophy", comment_count=8, timestamp=now),
            _make_post(3, "P3", channel="random", comment_count=1, timestamp=now),
        ])
        import compute_trending
        compute_trending.STATE_DIR = tmp_state
        compute_trending_from_log()
        trending = json.loads((tmp_state / "trending.json").read_text())
        assert trending["top_channels"][0]["channel"] == "philosophy"


class TestTrendingAgeFilter:
    """Test that old discussions are excluded from trending."""

    def test_old_posts_excluded(self, tmp_state):
        """Posts older than max_age_days don't appear in trending."""
        now = datetime.now(timezone.utc)
        old = (now - timedelta(days=60)).isoformat().replace("+00:00", "Z")
        recent = now.isoformat().replace("+00:00", "Z")

        _write_posted_log(tmp_state, [
            _make_post(1, "Old Post", comment_count=50, timestamp=old),
            _make_post(2, "Recent Post", upvotes=5, comment_count=2, timestamp=recent),
        ])

        import compute_trending
        compute_trending.STATE_DIR = tmp_state
        compute_trending_from_log(max_age_days=30)
        trending = json.loads((tmp_state / "trending.json").read_text())
        titles = [t["title"] for t in trending["trending"]]
        assert "Recent Post" in titles
        assert "Old Post" not in titles

    def test_recent_posts_kept(self, tmp_state):
        """Posts within max_age_days appear in trending."""
        now = datetime.now(timezone.utc)
        recent = (now - timedelta(days=5)).isoformat().replace("+00:00", "Z")

        _write_posted_log(tmp_state, [
            _make_post(1, "Fresh Post", upvotes=2, comment_count=3, timestamp=recent),
        ])

        import compute_trending
        compute_trending.STATE_DIR = tmp_state
        compute_trending_from_log(max_age_days=30)
        trending = json.loads((tmp_state / "trending.json").read_text())
        assert len(trending["trending"]) == 1
        assert trending["trending"][0]["title"] == "Fresh Post"
