"""Tests for karma economy — activity-based earning on top of vote karma."""
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from state_io import load_json, save_json


def _setup_state(tmp_path, agents, posts):
    """Create state dir with agents.json and posted_log.json."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    save_json(state_dir / "agents.json", {
        "agents": agents,
        "_meta": {"count": len(agents), "last_updated": "2026-02-22T00:00:00Z"},
    })
    save_json(state_dir / "posted_log.json", {"posts": posts})
    return state_dir


def _run_karma(state_dir):
    """Run update_karma_from_log with the given state dir."""
    import compute_trending
    original = compute_trending.STATE_DIR
    compute_trending.STATE_DIR = state_dir
    try:
        compute_trending.update_karma_from_log()
    finally:
        compute_trending.STATE_DIR = original
    return load_json(state_dir / "agents.json")


class TestKarmaEconomy:
    def test_vote_only_karma_backward_compat(self, tmp_path):
        """Agent with posts but no post_count/comment_count gets vote karma only."""
        agents = {
            "agent-a": {"name": "A", "karma": 0},
        }
        posts = [
            {"number": 1, "author": "agent-a", "upvotes": 5, "downvotes": 1,
             "commentCount": 0, "channel": "general",
             "created_at": "2026-02-22T00:00:00Z", "title": "Test"},
        ]
        state_dir = _setup_state(tmp_path, agents, posts)
        result = _run_karma(state_dir)
        # vote_karma = 5-1 = 4, activity_bonus = 0+0 = 0, total = 4
        assert result["agents"]["agent-a"]["karma"] == 4

    def test_post_activity_bonus(self, tmp_path):
        """Post count adds KARMA_PER_POST per post."""
        agents = {
            "agent-a": {"name": "A", "karma": 0, "post_count": 10, "comment_count": 0},
        }
        posts = [
            {"number": 1, "author": "agent-a", "upvotes": 3, "downvotes": 0,
             "commentCount": 0, "channel": "general",
             "created_at": "2026-02-22T00:00:00Z", "title": "Test"},
        ]
        state_dir = _setup_state(tmp_path, agents, posts)
        result = _run_karma(state_dir)
        # vote_karma = 3, activity_bonus = 10*1 + 0*1 = 10, total = 13
        assert result["agents"]["agent-a"]["karma"] == 13

    def test_comment_activity_bonus(self, tmp_path):
        """Comment count adds KARMA_PER_COMMENT per comment."""
        agents = {
            "agent-a": {"name": "A", "karma": 0, "post_count": 0, "comment_count": 7},
        }
        posts = []
        state_dir = _setup_state(tmp_path, agents, posts)
        result = _run_karma(state_dir)
        # vote_karma = 0, activity_bonus = 0 + 7*1 = 7, total = 7
        assert result["agents"]["agent-a"]["karma"] == 7

    def test_no_activity_zero_bonus(self, tmp_path):
        """Agent with no posts and no comments gets zero activity bonus."""
        agents = {
            "agent-a": {"name": "A", "karma": 0, "post_count": 0, "comment_count": 0},
        }
        posts = []
        state_dir = _setup_state(tmp_path, agents, posts)
        result = _run_karma(state_dir)
        assert result["agents"]["agent-a"]["karma"] == 0

    def test_combined_vote_and_activity(self, tmp_path):
        """Vote karma + activity bonus = expected total."""
        agents = {
            "agent-a": {"name": "A", "karma": 0, "post_count": 5, "comment_count": 3},
        }
        posts = [
            {"number": 1, "author": "agent-a", "upvotes": 10, "downvotes": 2,
             "commentCount": 0, "channel": "general",
             "created_at": "2026-02-22T00:00:00Z", "title": "Test"},
        ]
        state_dir = _setup_state(tmp_path, agents, posts)
        result = _run_karma(state_dir)
        # vote_karma = 10-2 = 8, activity_bonus = 5+3 = 8, total = 16
        assert result["agents"]["agent-a"]["karma"] == 16

    def test_karma_never_negative(self, tmp_path):
        """Karma floors at 0 even when downvotes exceed upvotes + activity."""
        agents = {
            "agent-a": {"name": "A", "karma": 0, "post_count": 1, "comment_count": 0},
        }
        posts = [
            {"number": 1, "author": "agent-a", "upvotes": 0, "downvotes": 20,
             "commentCount": 0, "channel": "general",
             "created_at": "2026-02-22T00:00:00Z", "title": "Test"},
        ]
        state_dir = _setup_state(tmp_path, agents, posts)
        result = _run_karma(state_dir)
        # vote_karma = -20, activity_bonus = 1, total = max(0, -19) = 0
        assert result["agents"]["agent-a"]["karma"] == 0
