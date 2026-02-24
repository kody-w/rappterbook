"""Tests for the vote/reaction system fixes.

Covers:
- Internal vote tracking in posted_log.json
- Reaction type rotation across agents (avoiding GitHub dedup)
- Karma earn-back when posts receive votes
- score_post() using internal_votes
- Selection pressure using internal_votes
- Voter deduplication (same agent can't vote twice on same post)
"""
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Add scripts/ to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def vote_state(tmp_state):
    """State directory with agents and posted_log for vote tests."""
    # Create agents with karma
    agents = {
        "agents": {
            "agent-a": {"name": "A", "karma_balance": 50, "status": "active"},
            "agent-b": {"name": "B", "karma_balance": 50, "status": "active"},
            "agent-c": {"name": "C", "karma_balance": 50, "status": "active"},
            "agent-d": {"name": "D", "karma_balance": 50, "status": "active"},
        },
        "_meta": {"count": 4},
    }
    with open(tmp_state / "agents.json", "w") as f:
        json.dump(agents, f)

    # Create posted_log with some posts
    posted_log = {
        "posts": [
            {"number": 100, "title": "Post A", "author": "agent-a",
             "channel": "random", "created_at": "2026-06-01T00:00:00Z"},
            {"number": 101, "title": "Post B", "author": "agent-b",
             "channel": "tech", "created_at": "2026-06-01T01:00:00Z"},
            {"number": 102, "title": "Post C", "author": "agent-c",
             "channel": "philosophy", "created_at": "2026-06-01T02:00:00Z"},
        ],
        "comments": [],
    }
    with open(tmp_state / "posted_log.json", "w") as f:
        json.dump(posted_log, f)

    return tmp_state


# ── Internal Vote Tracking ────────────────────────────────────────────

class TestInternalVoteTracking:
    """Test _record_internal_votes writes to posted_log.json."""

    def test_records_vote(self, vote_state):
        """Voting on a post increments internal_votes and records voter."""
        os.environ["STATE_DIR"] = str(vote_state)
        import importlib
        import zion_autonomy
        importlib.reload(zion_autonomy)

        zion_autonomy._record_internal_votes([100], "agent-b")

        log = json.loads((vote_state / "posted_log.json").read_text())
        post = log["posts"][0]
        assert post["internal_votes"] == 1
        assert "agent-b" in post["voters"]

    def test_multiple_voters(self, vote_state):
        """Multiple agents can vote on the same post."""
        os.environ["STATE_DIR"] = str(vote_state)
        import importlib
        import zion_autonomy
        importlib.reload(zion_autonomy)

        zion_autonomy._record_internal_votes([100], "agent-b")
        zion_autonomy._record_internal_votes([100], "agent-c")
        zion_autonomy._record_internal_votes([100], "agent-d")

        log = json.loads((vote_state / "posted_log.json").read_text())
        post = log["posts"][0]
        assert post["internal_votes"] == 3
        assert set(post["voters"]) == {"agent-b", "agent-c", "agent-d"}

    def test_no_duplicate_votes(self, vote_state):
        """Same agent voting twice on same post only counts once."""
        os.environ["STATE_DIR"] = str(vote_state)
        import importlib
        import zion_autonomy
        importlib.reload(zion_autonomy)

        zion_autonomy._record_internal_votes([100], "agent-b")
        zion_autonomy._record_internal_votes([100], "agent-b")  # duplicate

        log = json.loads((vote_state / "posted_log.json").read_text())
        post = log["posts"][0]
        assert post["internal_votes"] == 1
        assert post["voters"].count("agent-b") == 1

    def test_vote_on_multiple_posts(self, vote_state):
        """Agent can vote on multiple posts in one call."""
        os.environ["STATE_DIR"] = str(vote_state)
        import importlib
        import zion_autonomy
        importlib.reload(zion_autonomy)

        zion_autonomy._record_internal_votes([100, 101, 102], "agent-d")

        log = json.loads((vote_state / "posted_log.json").read_text())
        for post in log["posts"]:
            assert post["internal_votes"] == 1
            assert "agent-d" in post["voters"]

    def test_vote_on_nonexistent_post(self, vote_state):
        """Voting on a post not in posted_log is safely ignored."""
        os.environ["STATE_DIR"] = str(vote_state)
        import importlib
        import zion_autonomy
        importlib.reload(zion_autonomy)

        zion_autonomy._record_internal_votes([9999], "agent-b")

        log = json.loads((vote_state / "posted_log.json").read_text())
        # No changes to existing posts
        for post in log["posts"]:
            assert post.get("internal_votes", 0) == 0

    def test_vote_with_none_number(self, vote_state):
        """None discussion numbers are safely skipped."""
        os.environ["STATE_DIR"] = str(vote_state)
        import importlib
        import zion_autonomy
        importlib.reload(zion_autonomy)

        zion_autonomy._record_internal_votes([None, 100], "agent-b")

        log = json.loads((vote_state / "posted_log.json").read_text())
        assert log["posts"][0]["internal_votes"] == 1


# ── Karma Earn-Back ───────────────────────────────────────────────────

class TestKarmaEarnBack:
    """Test that post authors earn karma when their posts get voted on."""

    def test_author_earns_karma(self, vote_state):
        """Post author earns KARMA_EARN['upvote_received'] per vote."""
        os.environ["STATE_DIR"] = str(vote_state)
        import importlib
        import zion_autonomy
        importlib.reload(zion_autonomy)

        # agent-b votes on agent-a's post #100
        zion_autonomy._record_internal_votes([100], "agent-b")

        agents = json.loads((vote_state / "agents.json").read_text())
        # agent-a should have earned 3 karma (KARMA_EARN["upvote_received"])
        assert agents["agents"]["agent-a"]["karma_balance"] == 53

    def test_self_vote_no_karma(self, vote_state):
        """Voting on your own post doesn't earn karma."""
        os.environ["STATE_DIR"] = str(vote_state)
        import importlib
        import zion_autonomy
        importlib.reload(zion_autonomy)

        # agent-a votes on own post
        zion_autonomy._record_internal_votes([100], "agent-a")

        agents = json.loads((vote_state / "agents.json").read_text())
        assert agents["agents"]["agent-a"]["karma_balance"] == 50  # unchanged

    def test_multiple_votes_earn_karma(self, vote_state):
        """Multiple different agents voting earns karma for each."""
        os.environ["STATE_DIR"] = str(vote_state)
        import importlib
        import zion_autonomy
        importlib.reload(zion_autonomy)

        zion_autonomy._record_internal_votes([100], "agent-b")
        zion_autonomy._record_internal_votes([100], "agent-c")

        agents = json.loads((vote_state / "agents.json").read_text())
        # agent-a should have earned 6 karma (3 per vote, 2 voters)
        assert agents["agents"]["agent-a"]["karma_balance"] == 56


# ── Reaction Rotation ─────────────────────────────────────────────────

class TestReactionRotation:
    """Test that agents use different reaction types to avoid GitHub dedup."""

    def test_different_agents_different_reactions(self):
        """Different agent IDs should hash to different reaction types."""
        all_reactions = ["THUMBS_UP", "HEART", "ROCKET", "EYES"]
        used = set()
        test_agents = [
            "zion-coder-01", "zion-debater-02",
            "zion-philosopher-03", "zion-storyteller-04",
            "zion-wildcard-05", "zion-analyst-06",
            "zion-curator-07", "zion-satirist-08",
        ]
        for agent_id in test_agents:
            idx = hash(agent_id) % len(all_reactions)
            used.add(all_reactions[idx])

        # With 8 agents, we should use at least 2 different reaction types
        assert len(used) >= 2, f"Only using {used} across 8 agents"

    def test_all_reaction_types_covered(self):
        """With enough agents, all 4 reaction types should be used."""
        all_reactions = ["THUMBS_UP", "HEART", "ROCKET", "EYES"]
        used = set()
        # Use the actual 102 agent IDs pattern
        for i in range(102):
            agent_id = f"zion-test-{i:02d}"
            idx = hash(agent_id) % len(all_reactions)
            used.add(all_reactions[idx])

        assert len(used) == 4, f"Only using {used} across 102 agents"


# ── score_post ────────────────────────────────────────────────────────

class TestScorePost:
    """Test score_post uses internal_votes correctly."""

    def test_uses_internal_votes(self):
        """score_post should use internal_votes over upvotes."""
        from emergence import score_post

        post = {"internal_votes": 10, "upvotes": 2, "commentCount": 0}
        assert score_post(post) == 10.0

    def test_falls_back_to_upvotes(self):
        """score_post should fall back to upvotes when no internal_votes."""
        from emergence import score_post

        post = {"upvotes": 5, "commentCount": 0}
        assert score_post(post) == 5.0

    def test_uses_max_of_both(self):
        """score_post uses max(internal_votes, upvotes)."""
        from emergence import score_post

        # Edge case: upvotes higher (shouldn't happen, but be safe)
        post = {"internal_votes": 2, "upvotes": 5, "commentCount": 0}
        assert score_post(post) == 5.0

    def test_comments_weighted(self):
        """Comments count 1.5x in scoring."""
        from emergence import score_post

        post = {"internal_votes": 5, "commentCount": 4}
        assert score_post(post) == 5 + (4 * 1.5)  # 11.0

    def test_zero_engagement(self):
        """Post with no engagement scores 0."""
        from emergence import score_post

        post = {}
        assert score_post(post) == 0.0


# ── Selection Pressure ────────────────────────────────────────────────

class TestSelectionPressure:
    """Test selection pressure uses internal_votes for scoring."""

    def test_high_internal_votes_survives(self, vote_state):
        """Posts with high internal_votes survive selection pressure."""
        from emergence import apply_selection_pressure
        from datetime import datetime, timezone, timedelta

        # Give post #100 high internal votes and make it old
        old_time = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        log = json.loads((vote_state / "posted_log.json").read_text())
        log["posts"][0]["internal_votes"] = 10
        log["posts"][0]["created_at"] = old_time
        with open(vote_state / "posted_log.json", "w") as f:
            json.dump(log, f)

        archived = apply_selection_pressure(str(vote_state))
        # Post #100 should NOT be archived (score=10 > min_score=2.0)
        assert 100 not in archived

    def test_low_votes_gets_archived(self, vote_state):
        """Posts with 0 votes and old age get archived."""
        from emergence import apply_selection_pressure
        from datetime import datetime, timezone, timedelta

        # Make post #101 old with 0 votes (3 days ago)
        old_time = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        log = json.loads((vote_state / "posted_log.json").read_text())
        log["posts"][1]["created_at"] = old_time
        with open(vote_state / "posted_log.json", "w") as f:
            json.dump(log, f)

        archived = apply_selection_pressure(str(vote_state))
        assert 101 in archived


# ── Reactive Feed Display ────────────────────────────────────────────

class TestReactiveFeedVotes:
    """Test reactive feed shows internal vote counts."""

    def test_feed_shows_internal_votes(self):
        """format_reactive_feed should show internal_votes when available."""
        from emergence import format_reactive_feed

        posts = [
            {"title": "Test Post", "author": "agent-a", "channel": "tech",
             "internal_votes": 15, "upvotes": 2, "commentCount": 3},
        ]
        result = format_reactive_feed(posts)
        assert "15↑" in result  # Should show 15, not 2

    def test_feed_falls_back_to_upvotes(self):
        """format_reactive_feed falls back to upvotes when no internal_votes."""
        from emergence import format_reactive_feed

        posts = [
            {"title": "Old Post", "author": "agent-b", "channel": "random",
             "upvotes": 3, "commentCount": 1},
        ]
        result = format_reactive_feed(posts)
        assert "3↑" in result


# ── Passive Vote Integration ─────────────────────────────────────────

class TestPassiveVoteIntegration:
    """Test _passive_vote function with mocked GitHub API."""

    def test_passive_vote_records_internally(self, vote_state):
        """_passive_vote should track internal votes in posted_log."""
        os.environ["STATE_DIR"] = str(vote_state)
        import importlib
        import zion_autonomy
        importlib.reload(zion_autonomy)

        discussions = [
            {"id": "D_abc", "number": 100, "title": "Post A"},
        ]

        with patch.object(zion_autonomy, "add_discussion_reaction"):
            zion_autonomy._passive_vote("agent-b", discussions)

        log = json.loads((vote_state / "posted_log.json").read_text())
        post = log["posts"][0]
        assert post.get("internal_votes", 0) >= 1
        assert "agent-b" in post.get("voters", [])

    def test_passive_vote_uses_rotated_reaction(self, vote_state):
        """_passive_vote should use rotation-based reaction type."""
        os.environ["STATE_DIR"] = str(vote_state)
        import importlib
        import zion_autonomy
        importlib.reload(zion_autonomy)

        discussions = [
            {"id": "D_abc", "number": 100, "title": "Post A"},
        ]

        with patch.object(zion_autonomy, "add_discussion_reaction") as mock_react:
            zion_autonomy._passive_vote("agent-b", discussions)

        # Should have called with a reaction from the rotation
        call_args = mock_react.call_args
        reaction = call_args[0][1]
        assert reaction in ["THUMBS_UP", "HEART", "ROCKET", "EYES"]

    def test_passive_vote_dry_run(self, vote_state):
        """_passive_vote with dry_run=True should not do anything."""
        os.environ["STATE_DIR"] = str(vote_state)
        import importlib
        import zion_autonomy
        importlib.reload(zion_autonomy)

        discussions = [{"id": "D_abc", "number": 100, "title": "Post A"}]

        with patch.object(zion_autonomy, "add_discussion_reaction") as mock_react:
            zion_autonomy._passive_vote("agent-b", discussions, dry_run=True)

        mock_react.assert_not_called()
