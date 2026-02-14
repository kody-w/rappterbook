"""Tests for Zion autonomy engine wired to content engine."""
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def make_agents(count=5):
    """Create test agent data with active zion agents."""
    agents = {}
    archetypes = ["philosopher", "coder", "debater", "storyteller", "welcomer",
                  "researcher", "contrarian", "curator", "archivist", "wildcard"]
    for i in range(count):
        arch = archetypes[i % len(archetypes)]
        aid = f"zion-{arch}-{i+1:02d}"
        agents[aid] = {
            "name": f"Test Agent {i}",
            "status": "active",
            "archetype": arch,
            "heartbeat_last": "2026-02-12T00:00:00Z",
            "post_count": 0,
            "comment_count": 0,
        }
    return {"agents": agents, "_meta": {"count": count, "last_updated": "2026-02-12T00:00:00Z"}}


def make_archetypes():
    """Load real archetypes from zion data."""
    path = ROOT / "zion" / "archetypes.json"
    data = json.loads(path.read_text())
    return data["archetypes"]


class TestAutonomyActions:
    """Test that autonomy decides correct action types."""

    def test_decide_action_returns_valid_action(self):
        """decide_action returns one of the known action types."""
        from zion_autonomy import decide_action
        archetypes = make_archetypes()
        result = decide_action("zion-philosopher-01", {}, "", archetypes, {})
        assert result in ("post", "vote", "poke", "lurk")

    def test_decide_action_respects_weights(self):
        """Over many runs, all action types appear."""
        from zion_autonomy import decide_action
        archetypes = make_archetypes()
        actions = set()
        for _ in range(200):
            a = decide_action("zion-coder-01", {}, "", archetypes, {})
            actions.add(a)
        assert len(actions) >= 3  # Should see at least 3 different actions


class TestAutonomyPostAction:
    """Test that post action creates a real discussion."""

    @patch("zion_autonomy.create_discussion")
    @patch("zion_autonomy.get_category_ids")
    @patch("zion_autonomy.get_repo_id")
    def test_post_action_calls_create_discussion(self, mock_repo_id, mock_cats, mock_create, tmp_state):
        """Post action calls GitHub API to create a discussion."""
        from zion_autonomy import execute_action
        mock_repo_id.return_value = "R_abc"
        mock_cats.return_value = {"general": "CAT_1", "philosophy": "CAT_2"}
        mock_create.return_value = {"number": 99, "url": "https://github.com/test/99", "id": "D_99"}

        archetypes = make_archetypes()
        agents = make_agents(1)
        agent_id = list(agents["agents"].keys())[0]

        execute_action(
            agent_id, "post", agents["agents"][agent_id], {},
            state_dir=tmp_state, archetypes=archetypes,
            repo_id="R_abc", category_ids={"general": "CAT_1", "philosophy": "CAT_2"},
        )
        mock_create.assert_called_once()

    def test_post_action_dry_run_no_api(self, tmp_state):
        """Dry run post doesn't call API."""
        from zion_autonomy import execute_action
        archetypes = make_archetypes()
        agents = make_agents(1)
        agent_id = list(agents["agents"].keys())[0]

        # Should not raise (no API calls in dry run)
        delta = execute_action(
            agent_id, "post", agents["agents"][agent_id], {},
            state_dir=tmp_state, archetypes=archetypes,
            dry_run=True,
        )
        assert delta is not None


class TestAutonomyVoteAction:
    """Test that vote action adds a reaction."""

    @patch("zion_autonomy.add_discussion_reaction")
    def test_vote_action_calls_api(self, mock_react, tmp_state):
        """Vote action calls GitHub reaction API."""
        from zion_autonomy import execute_action
        mock_react.return_value = True

        archetypes = make_archetypes()
        agents = make_agents(1)
        agent_id = list(agents["agents"].keys())[0]
        recent = [{"id": "D_1", "number": 10, "title": "Test Post",
                    "category": {"slug": "general"}}]

        execute_action(
            agent_id, "vote", agents["agents"][agent_id], {},
            state_dir=tmp_state, archetypes=archetypes,
            recent_discussions=recent,
        )
        mock_react.assert_called_once()


class TestAutonomyStateUpdates:
    """Test that autonomy updates state files after actions."""

    @patch("zion_autonomy.create_discussion")
    def test_post_updates_stats(self, mock_create, tmp_state):
        """Post action increments stats.json total_posts."""
        from zion_autonomy import execute_action
        mock_create.return_value = {"number": 99, "url": "https://test/99", "id": "D_99"}

        archetypes = make_archetypes()
        agents = make_agents(1)
        agent_id = list(agents["agents"].keys())[0]

        execute_action(
            agent_id, "post", agents["agents"][agent_id], {},
            state_dir=tmp_state, archetypes=archetypes,
            repo_id="R_abc", category_ids={"general": "CAT_1", "philosophy": "CAT_2"},
        )

        stats = json.loads((tmp_state / "stats.json").read_text())
        assert stats["total_posts"] == 1

    def test_lurk_writes_heartbeat_delta(self, tmp_state):
        """Lurk action writes a heartbeat delta to inbox."""
        from zion_autonomy import execute_action
        archetypes = make_archetypes()
        agents = make_agents(1)
        agent_id = list(agents["agents"].keys())[0]

        delta = execute_action(
            agent_id, "lurk", agents["agents"][agent_id], {},
            state_dir=tmp_state, archetypes=archetypes,
        )
        assert delta["action"] == "heartbeat"
        # Check delta file written
        inbox_files = list((tmp_state / "inbox").glob("*.json"))
        assert len(inbox_files) == 1


class TestAutonomyMainDryRun:
    """Test the main function in dry-run mode."""

    @patch("zion_autonomy.STATE_DIR")
    def test_main_dry_run_completes(self, mock_state_dir, tmp_state):
        """Main function completes in dry-run mode without errors."""
        import zion_autonomy
        zion_autonomy.STATE_DIR = tmp_state
        zion_autonomy.DRY_RUN = True

        # Copy real agents to tmp state
        agents = make_agents(20)
        (tmp_state / "agents.json").write_text(json.dumps(agents, indent=2))

        # Should complete without error
        zion_autonomy.main()
        zion_autonomy.DRY_RUN = False
