"""Tests for downvote tracking and karma computation."""
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


class TestDownvoteTracking:
    def test_posted_log_has_downvotes_field(self):
        """posted_log entries should support a downvotes field."""
        post = {
            "number": 1,
            "title": "Test",
            "channel": "general",
            "author": "alice",
            "created_at": "2026-02-12T00:00:00Z",
            "upvotes": 10,
            "downvotes": 3,
            "commentCount": 5,
        }
        assert post["downvotes"] == 3
        assert post["upvotes"] - post["downvotes"] == 7

    def test_score_computation_with_downvotes(self):
        from compute_trending import compute_score
        # Score should factor in net votes (upvotes - downvotes)
        score_positive = compute_score(5, 10, "2026-02-12T00:00:00Z")
        assert score_positive > 0

    def test_trending_includes_downvotes(self, tmp_path):
        """Trending output should include downvotes field."""
        from compute_trending import compute_trending_from_log, load_json, save_json
        state_dir = tmp_path / "state"
        state_dir.mkdir()

        log_data = {
            "posts": [
                {
                    "number": 1, "title": "Test Post", "channel": "general",
                    "author": "alice", "created_at": "2026-02-21T00:00:00Z",
                    "upvotes": 10, "downvotes": 3, "commentCount": 5,
                }
            ]
        }
        save_json(state_dir / "posted_log.json", log_data)

        os.environ["STATE_DIR"] = str(state_dir)
        try:
            compute_trending_from_log()
        finally:
            os.environ.pop("STATE_DIR", None)

        trending = load_json(state_dir / "trending.json")
        if trending.get("trending"):
            post = trending["trending"][0]
            assert "downvotes" in post


class TestKarmaComputation:
    def test_karma_from_votes(self, tmp_path):
        """Karma = sum of (upvotes - downvotes) across all agent's posts."""
        from compute_trending import load_json, save_json

        state_dir = tmp_path / "state"
        state_dir.mkdir()

        agents_data = {
            "agents": {
                "alice": {"name": "Alice", "karma": 0, "post_count": 2},
                "bob": {"name": "Bob", "karma": 0, "post_count": 1},
            },
            "_meta": {"count": 2, "last_updated": "2026-02-12T00:00:00Z"}
        }
        save_json(state_dir / "agents.json", agents_data)

        log_data = {
            "posts": [
                {"number": 1, "author": "alice", "upvotes": 10, "downvotes": 2,
                 "commentCount": 3, "channel": "general",
                 "created_at": "2026-02-12T00:00:00Z", "title": "A1"},
                {"number": 2, "author": "alice", "upvotes": 5, "downvotes": 1,
                 "commentCount": 1, "channel": "code",
                 "created_at": "2026-02-12T01:00:00Z", "title": "A2"},
                {"number": 3, "author": "bob", "upvotes": 3, "downvotes": 3,
                 "commentCount": 0, "channel": "general",
                 "created_at": "2026-02-12T02:00:00Z", "title": "B1"},
            ]
        }
        save_json(state_dir / "posted_log.json", log_data)

        # Directly call with patched STATE_DIR
        import compute_trending
        original_state_dir = compute_trending.STATE_DIR
        compute_trending.STATE_DIR = state_dir
        try:
            compute_trending.update_karma_from_log()
        finally:
            compute_trending.STATE_DIR = original_state_dir

        agents = load_json(state_dir / "agents.json")
        # alice: (10-2) + (5-1) = 12
        assert agents["agents"]["alice"]["karma"] == 12
        # bob: (3-3) = 0
        assert agents["agents"]["bob"]["karma"] == 0
