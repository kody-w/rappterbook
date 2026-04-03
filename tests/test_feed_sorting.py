"""Tests for feed sorting and sorted feed generation."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from conftest import write_delta

ROOT = Path(__file__).resolve().parent.parent


class TestFeedAlgorithms:
    """Test the pure sort functions in feed_algorithms.py."""

    def test_sort_hot(self):
        from feed_algorithms import sort_hot
        posts = [
            {"title": "old", "upvotes": 10, "downvotes": 0, "created_at": "2026-01-01T00:00:00Z"},
            {"title": "new", "upvotes": 5, "downvotes": 0, "created_at": "2026-02-12T00:00:00Z"},
        ]
        result = sort_hot(posts)
        # Newer post with decent score should rank higher due to time boost
        assert result[0]["title"] == "new"

    def test_sort_new(self):
        from feed_algorithms import sort_new
        posts = [
            {"title": "old", "created_at": "2026-01-01T00:00:00Z"},
            {"title": "new", "created_at": "2026-02-12T00:00:00Z"},
        ]
        result = sort_new(posts)
        assert result[0]["title"] == "new"
        assert result[1]["title"] == "old"

    def test_sort_top(self):
        from feed_algorithms import sort_top
        posts = [
            {"title": "low", "upvotes": 2, "downvotes": 1, "created_at": "2026-02-12T00:00:00Z"},
            {"title": "high", "upvotes": 10, "downvotes": 0, "created_at": "2026-02-12T00:00:00Z"},
        ]
        result = sort_top(posts)
        assert result[0]["title"] == "high"

    def test_sort_top_time_range(self):
        from feed_algorithms import sort_top
        posts = [
            {"title": "old_high", "upvotes": 100, "downvotes": 0, "created_at": "2020-01-01T00:00:00Z"},
            {"title": "recent_low", "upvotes": 5, "downvotes": 0, "created_at": "2026-02-12T00:00:00Z"},
        ]
        result = sort_top(posts, time_range="week")
        # Old high-score post should be filtered out by time range
        titles = [p["title"] for p in result]
        assert "old_high" not in titles

    def test_sort_rising(self):
        from feed_algorithms import sort_rising
        posts = [
            {"title": "old_popular", "upvotes": 100, "downvotes": 0, "created_at": "2025-01-01T00:00:00Z"},
            {"title": "new_quick", "upvotes": 10, "downvotes": 0, "created_at": "2026-02-12T12:00:00Z"},
        ]
        result = sort_rising(posts)
        # New post with quick traction should rise
        assert result[0]["title"] == "new_quick"

    def test_filter_deleted(self):
        from feed_algorithms import sort_new
        posts = [
            {"title": "active", "created_at": "2026-02-12T00:00:00Z"},
            {"title": "deleted", "created_at": "2026-02-13T00:00:00Z", "is_deleted": True},
        ]
        result = sort_new(posts)
        assert len(result) == 2  # sort_new doesn't filter; sort_posts does

    def test_sort_posts_filters_deleted(self):
        from feed_algorithms import sort_posts
        posts = [
            {"title": "active", "created_at": "2026-02-12T00:00:00Z"},
            {"title": "deleted", "created_at": "2026-02-13T00:00:00Z", "is_deleted": True},
        ]
        result = sort_posts(posts, sort="new")
        assert len(result) == 1
        assert result[0]["title"] == "active"


class TestGenerateSortedFeeds:
    """Test the sorted feed generation in generate_feeds.py."""

    def test_generates_feed_files(self, tmp_state):
        """Sorted feeds should produce JSON files in STATE_DIR."""
        posted_log = {
            "posts": [
                {"number": 1, "title": "First", "author": "a1", "channel": "gen",
                 "upvotes": 5, "downvotes": 0, "created_at": "2026-02-12T00:00:00Z"},
                {"number": 2, "title": "Second", "author": "a2", "channel": "gen",
                 "upvotes": 10, "downvotes": 1, "created_at": "2026-02-12T01:00:00Z"},
                {"number": 3, "title": "Third", "author": "a3", "channel": "gen",
                 "upvotes": 3, "downvotes": 0, "created_at": "2026-02-12T02:00:00Z"},
            ]
        }
        (tmp_state / "posted_log.json").write_text(json.dumps(posted_log))

        env = os.environ.copy()
        env["STATE_DIR"] = str(tmp_state)
        env["DOCS_DIR"] = str(tmp_state / "docs")
        (tmp_state / "docs" / "feeds").mkdir(parents=True, exist_ok=True)

        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "generate_feeds.py"), "--sorted-feeds"],
            capture_output=True, text=True, env=env, cwd=str(ROOT)
        )

        assert (tmp_state / "feeds_hot.json").exists()
        assert (tmp_state / "feeds_new.json").exists()
        assert (tmp_state / "feeds_top.json").exists()
        assert (tmp_state / "feeds_rising.json").exists()

    def test_hot_feed_content(self, tmp_state):
        """Hot feed should contain sorted posts."""
        posted_log = {
            "posts": [
                {"number": 1, "title": "Cold", "author": "a1", "channel": "gen",
                 "upvotes": 1, "downvotes": 0, "created_at": "2020-01-01T00:00:00Z"},
                {"number": 2, "title": "Hot", "author": "a2", "channel": "gen",
                 "upvotes": 50, "downvotes": 0, "created_at": "2026-02-12T01:00:00Z"},
            ]
        }
        (tmp_state / "posted_log.json").write_text(json.dumps(posted_log))

        env = os.environ.copy()
        env["STATE_DIR"] = str(tmp_state)
        env["DOCS_DIR"] = str(tmp_state / "docs")
        (tmp_state / "docs" / "feeds").mkdir(parents=True, exist_ok=True)

        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "generate_feeds.py"), "--sorted-feeds"],
            capture_output=True, text=True, env=env, cwd=str(ROOT)
        )

        hot_feed = json.loads((tmp_state / "feeds_hot.json").read_text())
        assert hot_feed["sort"] == "hot"
        assert hot_feed["count"] == 2
        assert hot_feed["posts"][0]["title"] == "Hot"

    def test_new_feed_ordering(self, tmp_state):
        """New feed should be chronological, newest first."""
        posted_log = {
            "posts": [
                {"number": 1, "title": "Older", "author": "a1", "channel": "gen",
                 "created_at": "2026-02-12T00:00:00Z"},
                {"number": 2, "title": "Newer", "author": "a2", "channel": "gen",
                 "created_at": "2026-02-13T00:00:00Z"},
            ]
        }
        (tmp_state / "posted_log.json").write_text(json.dumps(posted_log))

        env = os.environ.copy()
        env["STATE_DIR"] = str(tmp_state)
        env["DOCS_DIR"] = str(tmp_state / "docs")
        (tmp_state / "docs" / "feeds").mkdir(parents=True, exist_ok=True)

        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "generate_feeds.py"), "--sorted-feeds"],
            capture_output=True, text=True, env=env, cwd=str(ROOT)
        )

        new_feed = json.loads((tmp_state / "feeds_new.json").read_text())
        assert new_feed["posts"][0]["title"] == "Newer"

    def test_time_filtered_top_feeds(self, tmp_state):
        """Time-filtered top feeds should be generated."""
        posted_log = {"posts": [
            {"number": 1, "title": "P", "author": "a", "channel": "g",
             "upvotes": 1, "created_at": "2026-02-12T00:00:00Z"}
        ]}
        (tmp_state / "posted_log.json").write_text(json.dumps(posted_log))

        env = os.environ.copy()
        env["STATE_DIR"] = str(tmp_state)
        env["DOCS_DIR"] = str(tmp_state / "docs")
        (tmp_state / "docs" / "feeds").mkdir(parents=True, exist_ok=True)

        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "generate_feeds.py"), "--sorted-feeds"],
            capture_output=True, text=True, env=env, cwd=str(ROOT)
        )

        for period in ("hour", "day", "week", "month"):
            assert (tmp_state / f"feeds_top_{period}.json").exists()
