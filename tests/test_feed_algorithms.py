"""Tests for feed ranking algorithms — hot, new, top, rising, controversial, best."""
import json
import math
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


class TestHotAlgorithm:
    def test_higher_score_ranks_higher(self):
        from feed_algorithms import hot_score
        now = datetime.now(timezone.utc).isoformat()
        assert hot_score(100, 10, now) > hot_score(10, 1, now)

    def test_newer_post_beats_older_equal_score(self):
        from feed_algorithms import hot_score
        old = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        new = datetime.now(timezone.utc).isoformat()
        assert hot_score(10, 5, new) > hot_score(10, 5, old)

    def test_zero_score_still_ranks(self):
        from feed_algorithms import hot_score
        now = datetime.now(timezone.utc).isoformat()
        score = hot_score(0, 0, now)
        assert isinstance(score, float)


class TestNewAlgorithm:
    def test_newest_first(self):
        from feed_algorithms import sort_new
        posts = [
            {"created_at": "2026-02-10T00:00:00Z", "title": "old"},
            {"created_at": "2026-02-12T00:00:00Z", "title": "new"},
            {"created_at": "2026-02-11T00:00:00Z", "title": "mid"},
        ]
        result = sort_new(posts)
        assert result[0]["title"] == "new"
        assert result[-1]["title"] == "old"


class TestTopAlgorithm:
    def test_highest_score_first(self):
        from feed_algorithms import sort_top
        posts = [
            {"upvotes": 5, "downvotes": 2, "title": "mid"},
            {"upvotes": 20, "downvotes": 1, "title": "top"},
            {"upvotes": 3, "downvotes": 3, "title": "low"},
        ]
        result = sort_top(posts)
        assert result[0]["title"] == "top"
        assert result[-1]["title"] == "low"

    def test_time_filter_hour(self):
        from feed_algorithms import sort_top
        old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        recent = datetime.now(timezone.utc).isoformat()
        posts = [
            {"upvotes": 100, "downvotes": 0, "title": "old-high", "created_at": old},
            {"upvotes": 5, "downvotes": 0, "title": "new-low", "created_at": recent},
        ]
        result = sort_top(posts, time_range="hour")
        assert len(result) == 1
        assert result[0]["title"] == "new-low"

    def test_time_filter_all(self):
        from feed_algorithms import sort_top
        old = "2020-01-01T00:00:00Z"
        posts = [
            {"upvotes": 100, "downvotes": 0, "title": "ancient", "created_at": old},
        ]
        result = sort_top(posts, time_range="all")
        assert len(result) == 1


class TestRisingAlgorithm:
    def test_young_high_score_beats_old(self):
        from feed_algorithms import sort_rising
        old = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        new = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        posts = [
            {"upvotes": 50, "downvotes": 5, "title": "old", "created_at": old},
            {"upvotes": 20, "downvotes": 2, "title": "new", "created_at": new},
        ]
        result = sort_rising(posts)
        assert result[0]["title"] == "new"


class TestControversialAlgorithm:
    def test_even_split_ranks_highest(self):
        from feed_algorithms import controversial_score
        # 50/50 split with high volume
        even = controversial_score(50, 50)
        # 90/10 split with same volume
        lopsided = controversial_score(90, 10)
        assert even > lopsided

    def test_zero_votes_returns_zero(self):
        from feed_algorithms import controversial_score
        assert controversial_score(0, 0) == 0

    def test_sort_controversial(self):
        from feed_algorithms import sort_controversial
        posts = [
            {"upvotes": 50, "downvotes": 50, "title": "controversial", "created_at": "2026-02-12T00:00:00Z"},
            {"upvotes": 100, "downvotes": 1, "title": "popular", "created_at": "2026-02-12T00:00:00Z"},
            {"upvotes": 1, "downvotes": 0, "title": "boring", "created_at": "2026-02-12T00:00:00Z"},
        ]
        result = sort_controversial(posts)
        assert result[0]["title"] == "controversial"


class TestBestAlgorithm:
    def test_wilson_high_confidence(self):
        from feed_algorithms import wilson_score
        # Many votes, high ratio
        high = wilson_score(100, 5)
        # Few votes, same ratio
        low = wilson_score(10, 0)
        assert high > low

    def test_wilson_zero_votes(self):
        from feed_algorithms import wilson_score
        assert wilson_score(0, 0) == 0.0

    def test_sort_best(self):
        from feed_algorithms import sort_best
        posts = [
            {"upvotes": 100, "downvotes": 5, "title": "confident-good"},
            {"upvotes": 3, "downvotes": 0, "title": "few-votes"},
            {"upvotes": 50, "downvotes": 45, "title": "uncertain"},
        ]
        result = sort_best(posts)
        assert result[0]["title"] == "confident-good"


class TestSortPosts:
    def test_all_sort_modes(self):
        from feed_algorithms import sort_posts
        posts = [
            {"upvotes": 10, "downvotes": 2, "title": "a",
             "created_at": "2026-02-12T00:00:00Z", "commentCount": 5},
            {"upvotes": 5, "downvotes": 1, "title": "b",
             "created_at": "2026-02-11T00:00:00Z", "commentCount": 2},
        ]
        for mode in ["hot", "new", "top", "rising", "controversial", "best"]:
            result = sort_posts(posts, sort=mode)
            assert len(result) == 2, f"sort={mode} returned wrong count"

    def test_invalid_sort_defaults_to_hot(self):
        from feed_algorithms import sort_posts
        posts = [{"upvotes": 1, "downvotes": 0, "title": "a",
                  "created_at": "2026-02-12T00:00:00Z", "commentCount": 0}]
        result = sort_posts(posts, sort="invalid")
        assert len(result) == 1


class TestPersonalizedFeed:
    def test_filter_by_channels(self):
        from feed_algorithms import personalized_feed
        posts = [
            {"channel": "code", "title": "a", "upvotes": 1, "downvotes": 0,
             "created_at": "2026-02-12T00:00:00Z", "author": "x", "commentCount": 0},
            {"channel": "philosophy", "title": "b", "upvotes": 1, "downvotes": 0,
             "created_at": "2026-02-12T00:00:00Z", "author": "y", "commentCount": 0},
        ]
        result = personalized_feed(posts, subscribed_channels=["code"],
                                   followed_agents=[], sort="new")
        assert len(result) == 1
        assert result[0]["title"] == "a"

    def test_filter_by_followed_agents(self):
        from feed_algorithms import personalized_feed
        posts = [
            {"channel": "general", "title": "a", "upvotes": 1, "downvotes": 0,
             "created_at": "2026-02-12T00:00:00Z", "author": "alice", "commentCount": 0},
            {"channel": "general", "title": "b", "upvotes": 1, "downvotes": 0,
             "created_at": "2026-02-12T00:00:00Z", "author": "bob", "commentCount": 0},
        ]
        result = personalized_feed(posts, subscribed_channels=[],
                                   followed_agents=["alice"], sort="new")
        assert len(result) == 1
        assert result[0]["author"] == "alice"

    def test_union_of_channels_and_agents(self):
        from feed_algorithms import personalized_feed
        posts = [
            {"channel": "code", "title": "a", "upvotes": 1, "downvotes": 0,
             "created_at": "2026-02-12T00:00:00Z", "author": "alice", "commentCount": 0},
            {"channel": "philosophy", "title": "b", "upvotes": 1, "downvotes": 0,
             "created_at": "2026-02-12T00:00:00Z", "author": "bob", "commentCount": 0},
            {"channel": "stories", "title": "c", "upvotes": 1, "downvotes": 0,
             "created_at": "2026-02-12T00:00:00Z", "author": "charlie", "commentCount": 0},
        ]
        result = personalized_feed(posts, subscribed_channels=["code"],
                                   followed_agents=["bob"], sort="new")
        assert len(result) == 2
