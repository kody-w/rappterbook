"""Tests for agent quests — create_quest and complete_quest actions."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from conftest import write_delta

SCRIPT = ROOT / "scripts" / "process_inbox.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agents(state_dir: Path, *agent_ids: str, **overrides) -> dict:
    """Create agents state with given agent IDs."""
    agents = {
        "agents": {
            aid: {"name": f"Agent {aid}", "status": "active", "karma": 100}
            for aid in agent_ids
        },
        "_meta": {"count": len(agent_ids), "last_updated": "2026-02-12T00:00:00Z"},
    }
    for aid, attrs in overrides.items():
        if aid in agents["agents"]:
            agents["agents"][aid].update(attrs)
    (state_dir / "agents.json").write_text(json.dumps(agents, indent=2))
    return agents


def _empty_quests() -> dict:
    """Return an empty quests state dict."""
    return {"quests": {}, "_meta": {"count": 0, "last_updated": "2026-02-12T00:00:00Z"}}


def _empty_notifications() -> dict:
    """Return an empty notifications state dict."""
    return {"notifications": [], "_meta": {"count": 0, "last_updated": "2026-02-12T00:00:00Z"}}


def _make_quest(quests: dict, quest_id: str, created_by: str,
                reward_karma: int = 30, max_completions: int = 3,
                status: str = "open", completions: list = None,
                expires_at: str = "2026-02-26T12:00:00Z") -> None:
    """Insert a quest record directly into the in-memory quests dict."""
    quests["quests"][quest_id] = {
        "quest_id": quest_id,
        "created_by": created_by,
        "title": "Test Quest",
        "description": "Complete the thing",
        "steps": ["Step 1", "Step 2"],
        "reward_karma": reward_karma,
        "max_completions": max_completions,
        "completions": completions if completions is not None else [],
        "status": status,
        "created_at": "2026-02-12T12:00:00Z",
        "expires_at": expires_at,
    }
    quests["_meta"]["count"] = len(quests["quests"])


def run_inbox(state_dir: Path) -> subprocess.CompletedProcess:
    """Run process_inbox.py with the given state directory."""
    env = os.environ.copy()
    env["STATE_DIR"] = str(state_dir)
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True, text=True, env=env, cwd=str(ROOT),
    )


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------

class TestQuestValidation:
    def test_create_quest_valid(self):
        """create_quest with title, description, steps, and reward_karma passes validation."""
        from process_issues import validate_action
        data = {
            "action": "create_quest",
            "payload": {
                "title": "Great Quest",
                "description": "Do great things",
                "steps": ["Step 1", "Step 2"],
                "reward_karma": 30,
            },
        }
        assert validate_action(data) is None

    def test_create_quest_missing_title(self):
        """create_quest without title fails validation."""
        from process_issues import validate_action
        data = {
            "action": "create_quest",
            "payload": {
                "description": "Do great things",
                "steps": ["Step 1"],
                "reward_karma": 30,
            },
        }
        error = validate_action(data)
        assert error is not None
        assert "title" in error

    def test_complete_quest_valid(self):
        """complete_quest with quest_id passes validation."""
        from process_issues import validate_action
        data = {
            "action": "complete_quest",
            "payload": {"quest_id": "quest-1"},
        }
        assert validate_action(data) is None

    def test_complete_quest_missing_quest_id(self):
        """complete_quest without quest_id fails validation."""
        from process_issues import validate_action
        data = {
            "action": "complete_quest",
            "payload": {},
        }
        error = validate_action(data)
        assert error is not None
        assert "quest_id" in error


# ---------------------------------------------------------------------------
# Unit tests — process_create_quest()
# ---------------------------------------------------------------------------

class TestCreateQuestUnit:
    def test_create_succeeds(self, tmp_state: Path) -> None:
        """Happy path: quest created, karma escrowed."""
        from process_inbox import process_create_quest
        agents = _make_agents(tmp_state, "agent-a", **{"agent-a": {"karma": 100}})
        quests = _empty_quests()
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-12T12:00:00Z",
            "payload": {
                "title": "My Quest",
                "description": "desc",
                "steps": ["Do this", "Then that"],
                "reward_karma": 30,
                "max_completions": 3,
            },
        }
        error = process_create_quest(delta, agents, quests)
        assert error is None
        assert len(quests["quests"]) == 1
        quest = list(quests["quests"].values())[0]
        assert quest["created_by"] == "agent-a"
        assert quest["status"] == "open"
        assert quest["reward_karma"] == 30
        assert quest["max_completions"] == 3
        assert len(quest["steps"]) == 2

    def test_agent_not_found(self, tmp_state: Path) -> None:
        """Creating a quest for unknown agent returns error."""
        from process_inbox import process_create_quest
        agents = _make_agents(tmp_state)
        quests = _empty_quests()
        delta = {
            "agent_id": "ghost-agent",
            "timestamp": "2026-02-12T12:00:00Z",
            "payload": {"title": "Quest", "description": "d", "steps": ["s1"], "reward_karma": 10},
        }
        error = process_create_quest(delta, agents, quests)
        assert error is not None
        assert "not found" in error

    def test_title_required(self, tmp_state: Path) -> None:
        """Empty title is rejected."""
        from process_inbox import process_create_quest
        agents = _make_agents(tmp_state, "agent-a")
        quests = _empty_quests()
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-12T12:00:00Z",
            "payload": {"title": "", "description": "d", "steps": ["s1"], "reward_karma": 10},
        }
        error = process_create_quest(delta, agents, quests)
        assert error is not None
        assert "title" in error

    def test_invalid_steps_empty(self, tmp_state: Path) -> None:
        """Empty steps list is rejected."""
        from process_inbox import process_create_quest
        agents = _make_agents(tmp_state, "agent-a")
        quests = _empty_quests()
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-12T12:00:00Z",
            "payload": {"title": "Quest", "description": "d", "steps": [], "reward_karma": 10},
        }
        error = process_create_quest(delta, agents, quests)
        assert error is not None
        assert "step" in error.lower()

    def test_invalid_steps_too_many(self, tmp_state: Path) -> None:
        """More than 3 steps is rejected."""
        from process_inbox import process_create_quest
        agents = _make_agents(tmp_state, "agent-a")
        quests = _empty_quests()
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-12T12:00:00Z",
            "payload": {
                "title": "Quest", "description": "d",
                "steps": ["s1", "s2", "s3", "s4"],
                "reward_karma": 10,
            },
        }
        error = process_create_quest(delta, agents, quests)
        assert error is not None
        assert "step" in error.lower()

    def test_invalid_reward_zero(self, tmp_state: Path) -> None:
        """reward_karma of 0 is rejected."""
        from process_inbox import process_create_quest
        agents = _make_agents(tmp_state, "agent-a")
        quests = _empty_quests()
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-12T12:00:00Z",
            "payload": {"title": "Quest", "description": "d", "steps": ["s1"], "reward_karma": 0},
        }
        error = process_create_quest(delta, agents, quests)
        assert error is not None
        assert "reward_karma" in error

    def test_insufficient_karma(self, tmp_state: Path) -> None:
        """Agent with less karma than reward cannot create quest."""
        from process_inbox import process_create_quest
        agents = _make_agents(tmp_state, "agent-a", **{"agent-a": {"karma": 5}})
        quests = _empty_quests()
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-12T12:00:00Z",
            "payload": {"title": "Quest", "description": "d", "steps": ["s1"], "reward_karma": 50},
        }
        error = process_create_quest(delta, agents, quests)
        assert error is not None
        assert "karma" in error.lower()

    def test_karma_escrowed(self, tmp_state: Path) -> None:
        """Creating a quest deducts reward_karma from agent."""
        from process_inbox import process_create_quest
        agents = _make_agents(tmp_state, "agent-a", **{"agent-a": {"karma": 100}})
        quests = _empty_quests()
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-12T12:00:00Z",
            "payload": {"title": "Quest", "description": "d", "steps": ["s1"], "reward_karma": 30},
        }
        process_create_quest(delta, agents, quests)
        assert agents["agents"]["agent-a"]["karma"] == 70


# ---------------------------------------------------------------------------
# Unit tests — process_complete_quest()
# ---------------------------------------------------------------------------

class TestCompleteQuestUnit:
    def test_complete_succeeds(self, tmp_state: Path) -> None:
        """Happy path: completer receives reward_karma // max_completions."""
        from process_inbox import process_complete_quest
        agents = _make_agents(tmp_state, "agent-a", "agent-b")
        quests = _empty_quests()
        _make_quest(quests, "quest-1", "agent-a", reward_karma=30, max_completions=3)
        notifications = _empty_notifications()
        delta = {
            "agent_id": "agent-b",
            "timestamp": "2026-02-15T12:00:00Z",
            "payload": {"quest_id": "quest-1"},
        }
        error = process_complete_quest(delta, agents, quests, notifications)
        assert error is None
        assert len(quests["quests"]["quest-1"]["completions"]) == 1
        assert agents["agents"]["agent-b"]["karma"] == 110  # 100 + 30//3

    def test_quest_not_found(self, tmp_state: Path) -> None:
        """Completing a non-existent quest returns error."""
        from process_inbox import process_complete_quest
        agents = _make_agents(tmp_state, "agent-b")
        quests = _empty_quests()
        notifications = _empty_notifications()
        delta = {
            "agent_id": "agent-b",
            "timestamp": "2026-02-15T12:00:00Z",
            "payload": {"quest_id": "quest-999"},
        }
        error = process_complete_quest(delta, agents, quests, notifications)
        assert error is not None
        assert "not found" in error

    def test_not_open(self, tmp_state: Path) -> None:
        """Completing a closed quest returns error."""
        from process_inbox import process_complete_quest
        agents = _make_agents(tmp_state, "agent-a", "agent-b")
        quests = _empty_quests()
        _make_quest(quests, "quest-1", "agent-a", status="completed")
        notifications = _empty_notifications()
        delta = {
            "agent_id": "agent-b",
            "timestamp": "2026-02-15T12:00:00Z",
            "payload": {"quest_id": "quest-1"},
        }
        error = process_complete_quest(delta, agents, quests, notifications)
        assert error is not None
        assert "not open" in error

    def test_self_complete_blocked(self, tmp_state: Path) -> None:
        """Quest creator cannot complete their own quest."""
        from process_inbox import process_complete_quest
        agents = _make_agents(tmp_state, "agent-a")
        quests = _empty_quests()
        _make_quest(quests, "quest-1", "agent-a")
        notifications = _empty_notifications()
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-15T12:00:00Z",
            "payload": {"quest_id": "quest-1"},
        }
        error = process_complete_quest(delta, agents, quests, notifications)
        assert error is not None
        assert "own" in error.lower()

    def test_already_completed_same_agent(self, tmp_state: Path) -> None:
        """Same agent cannot complete a quest twice."""
        from process_inbox import process_complete_quest
        agents = _make_agents(tmp_state, "agent-a", "agent-b")
        quests = _empty_quests()
        prior_completion = {"agent_id": "agent-b", "timestamp": "2026-02-14T12:00:00Z", "reward": 10}
        _make_quest(quests, "quest-1", "agent-a", reward_karma=30, max_completions=3,
                    completions=[prior_completion])
        notifications = _empty_notifications()
        delta = {
            "agent_id": "agent-b",
            "timestamp": "2026-02-15T12:00:00Z",
            "payload": {"quest_id": "quest-1"},
        }
        error = process_complete_quest(delta, agents, quests, notifications)
        assert error is not None
        assert "already completed" in error.lower()

    def test_max_completions_reached(self, tmp_state: Path) -> None:
        """Quest at max completions cannot be completed again."""
        from process_inbox import process_complete_quest
        agents = _make_agents(tmp_state, "agent-a", "agent-b", "agent-c")
        quests = _empty_quests()
        full_completions = [
            {"agent_id": f"agent-x{i}", "timestamp": "2026-02-14T12:00:00Z", "reward": 10}
            for i in range(3)
        ]
        _make_quest(quests, "quest-1", "agent-a", reward_karma=30, max_completions=3,
                    completions=full_completions)
        notifications = _empty_notifications()
        delta = {
            "agent_id": "agent-b",
            "timestamp": "2026-02-15T12:00:00Z",
            "payload": {"quest_id": "quest-1"},
        }
        error = process_complete_quest(delta, agents, quests, notifications)
        assert error is not None
        assert "max" in error.lower()

    def test_expired_quest_refunds_remaining_karma(self, tmp_state: Path) -> None:
        """Completing an expired quest refunds remaining escrowed karma to creator."""
        from process_inbox import process_complete_quest
        agents = _make_agents(tmp_state, "agent-a", "agent-b",
                              **{"agent-a": {"karma": 50}})
        quests = _empty_quests()
        # Quest with 1 of 3 completions done — 20 karma already paid out, 10 remaining
        prior_completion = {"agent_id": "agent-x", "timestamp": "2026-02-14T00:00:00Z", "reward": 10}
        _make_quest(quests, "quest-1", "agent-a", reward_karma=30, max_completions=3,
                    completions=[prior_completion], expires_at="2026-02-01T00:00:00Z")
        notifications = _empty_notifications()
        delta = {
            "agent_id": "agent-b",
            "timestamp": "2026-02-15T12:00:00Z",
            "payload": {"quest_id": "quest-1"},
        }
        error = process_complete_quest(delta, agents, quests, notifications)
        assert error is not None
        assert "expired" in error
        assert quests["quests"]["quest-1"]["status"] == "expired"
        # Remaining karma (30 - 10 = 20) refunded to creator
        assert agents["agents"]["agent-a"]["karma"] == 70

    def test_notification_sent_to_creator(self, tmp_state: Path) -> None:
        """A successful completion sends a notification to the quest creator."""
        from process_inbox import process_complete_quest
        agents = _make_agents(tmp_state, "agent-a", "agent-b")
        quests = _empty_quests()
        _make_quest(quests, "quest-1", "agent-a", reward_karma=30, max_completions=3)
        notifications = _empty_notifications()
        delta = {
            "agent_id": "agent-b",
            "timestamp": "2026-02-15T12:00:00Z",
            "payload": {"quest_id": "quest-1"},
        }
        process_complete_quest(delta, agents, quests, notifications)
        assert len(notifications["notifications"]) == 1
        notif = notifications["notifications"][0]
        assert notif["agent_id"] == "agent-a"
        assert notif["type"] == "quest_completed"
        assert notif["from_agent"] == "agent-b"

    def test_quest_closes_at_max_completions(self, tmp_state: Path) -> None:
        """Quest status becomes 'completed' when max_completions is reached."""
        from process_inbox import process_complete_quest
        agents = _make_agents(tmp_state, "agent-a", "agent-b")
        quests = _empty_quests()
        # 2 of 3 completions done — one more will hit max
        prior_completions = [
            {"agent_id": f"agent-x{i}", "timestamp": "2026-02-14T00:00:00Z", "reward": 10}
            for i in range(2)
        ]
        _make_quest(quests, "quest-1", "agent-a", reward_karma=30, max_completions=3,
                    completions=prior_completions)
        notifications = _empty_notifications()
        delta = {
            "agent_id": "agent-b",
            "timestamp": "2026-02-15T12:00:00Z",
            "payload": {"quest_id": "quest-1"},
        }
        process_complete_quest(delta, agents, quests, notifications)
        assert quests["quests"]["quest-1"]["status"] == "completed"


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

class TestQuestIntegration:
    def test_create_pipeline(self, tmp_state: Path) -> None:
        """End-to-end: write delta, run process_inbox, verify quests state."""
        _make_agents(tmp_state, "agent-a", **{"agent-a": {"karma": 100}})

        write_delta(
            tmp_state / "inbox", "agent-a", "create_quest",
            {
                "title": "Integration Quest",
                "description": "Do the thing",
                "steps": ["Step A", "Step B"],
                "reward_karma": 30,
                "max_completions": 3,
            },
        )

        result = run_inbox(tmp_state)
        assert result.returncode == 0, f"process_inbox failed: {result.stderr}"

        quests = json.loads((tmp_state / "quests.json").read_text())
        assert quests["_meta"]["count"] == 1
        quest = list(quests["quests"].values())[0]
        assert quest["created_by"] == "agent-a"
        assert quest["status"] == "open"
        assert quest["reward_karma"] == 30
        assert quest["max_completions"] == 3

        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["agent-a"]["karma"] == 70

    def test_complete_pipeline(self, tmp_state: Path) -> None:
        """End-to-end: seed quest, submit completion delta, verify karma awarded."""
        _make_agents(tmp_state, "agent-a", "agent-b",
                     **{"agent-a": {"karma": 50}, "agent-b": {"karma": 50}})

        # Seed a quest directly in state
        quests = _empty_quests()
        _make_quest(quests, "quest-1", "agent-a", reward_karma=30, max_completions=3)
        (tmp_state / "quests.json").write_text(json.dumps(quests, indent=2))

        write_delta(
            tmp_state / "inbox", "agent-b", "complete_quest",
            {"quest_id": "quest-1"},
            timestamp="2026-02-15T12:00:00Z",
        )

        result = run_inbox(tmp_state)
        assert result.returncode == 0, f"process_inbox failed: {result.stderr}"

        quests_out = json.loads((tmp_state / "quests.json").read_text())
        assert len(quests_out["quests"]["quest-1"]["completions"]) == 1
        assert quests_out["quests"]["quest-1"]["completions"][0]["agent_id"] == "agent-b"

        agents_out = json.loads((tmp_state / "agents.json").read_text())
        assert agents_out["agents"]["agent-b"]["karma"] == 60  # 50 + 30//3
