"""Tests for autonomous bounties — post_bounty and claim_bounty actions."""
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


def _make_bounty(bounties: dict, bounty_id: str, posted_by: str,
                 reward: int = 10, status: str = "open") -> None:
    """Insert a bounty record directly into the in-memory bounties dict."""
    bounties["bounties"][bounty_id] = {
        "bounty_id": bounty_id,
        "posted_by": posted_by,
        "title": "Test Bounty",
        "description": "Do a thing",
        "reward_karma": reward,
        "status": status,
        "created_at": "2026-02-12T12:00:00Z",
        "expires_at": "2026-02-19T12:00:00Z",
        "claimed_by": None,
        "claimed_at": None,
    }
    bounties["_meta"]["count"] = len(bounties["bounties"])


def _empty_bounties() -> dict:
    """Return an empty bounties state dict."""
    return {"bounties": {}, "_meta": {"count": 0, "last_updated": "2026-02-12T00:00:00Z"}}


def _empty_notifications() -> dict:
    """Return an empty notifications state dict."""
    return {"notifications": [], "_meta": {"count": 0, "last_updated": "2026-02-12T00:00:00Z"}}


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

class TestBountyValidation:
    def test_post_bounty_valid(self):
        """post_bounty with title, description, and reward_karma passes validation."""
        from process_issues import validate_action
        data = {
            "action": "post_bounty",
            "payload": {"title": "Fix the bug", "description": "Describe steps", "reward_karma": 10},
        }
        assert validate_action(data) is None

    def test_post_bounty_missing_title(self):
        """post_bounty without title fails validation."""
        from process_issues import validate_action
        data = {
            "action": "post_bounty",
            "payload": {"description": "Describe steps", "reward_karma": 10},
        }
        error = validate_action(data)
        assert error is not None
        assert "title" in error

    def test_post_bounty_missing_reward_karma(self):
        """post_bounty without reward_karma fails validation."""
        from process_issues import validate_action
        data = {
            "action": "post_bounty",
            "payload": {"title": "Fix the bug", "description": "Describe steps"},
        }
        error = validate_action(data)
        assert error is not None
        assert "reward_karma" in error

    def test_claim_bounty_valid(self):
        """claim_bounty with bounty_id passes validation."""
        from process_issues import validate_action
        data = {
            "action": "claim_bounty",
            "payload": {"bounty_id": "bounty-1"},
        }
        assert validate_action(data) is None

    def test_claim_bounty_missing_bounty_id(self):
        """claim_bounty without bounty_id fails validation."""
        from process_issues import validate_action
        data = {
            "action": "claim_bounty",
            "payload": {},
        }
        error = validate_action(data)
        assert error is not None
        assert "bounty_id" in error


# ---------------------------------------------------------------------------
# Unit tests — process_post_bounty()
# ---------------------------------------------------------------------------

class TestPostBountyUnit:
    def test_post_succeeds(self, tmp_state: Path) -> None:
        """Happy path: valid bounty is created and karma is escrowed."""
        from process_inbox import process_post_bounty
        agents = _make_agents(tmp_state, "agent-a")
        bounties = _empty_bounties()
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-12T12:00:00Z",
            "payload": {"title": "Fix the auth bug", "description": "Steps inside", "reward_karma": 20},
        }
        error = process_post_bounty(delta, agents, bounties)
        assert error is None
        assert len(bounties["bounties"]) == 1
        bounty = list(bounties["bounties"].values())[0]
        assert bounty["posted_by"] == "agent-a"
        assert bounty["status"] == "open"
        assert bounty["reward_karma"] == 20

    def test_agent_not_found(self, tmp_state: Path) -> None:
        """Posting bounty for unknown agent returns error."""
        from process_inbox import process_post_bounty
        agents = _make_agents(tmp_state)
        bounties = _empty_bounties()
        delta = {
            "agent_id": "ghost-agent",
            "timestamp": "2026-02-12T12:00:00Z",
            "payload": {"title": "Do thing", "description": "desc", "reward_karma": 5},
        }
        error = process_post_bounty(delta, agents, bounties)
        assert error is not None
        assert "not found" in error

    def test_title_required(self, tmp_state: Path) -> None:
        """Empty title is rejected."""
        from process_inbox import process_post_bounty
        agents = _make_agents(tmp_state, "agent-a")
        bounties = _empty_bounties()
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-12T12:00:00Z",
            "payload": {"title": "", "description": "desc", "reward_karma": 5},
        }
        error = process_post_bounty(delta, agents, bounties)
        assert error is not None
        assert "title" in error

    def test_invalid_reward_zero(self, tmp_state: Path) -> None:
        """reward_karma of 0 is rejected."""
        from process_inbox import process_post_bounty
        agents = _make_agents(tmp_state, "agent-a")
        bounties = _empty_bounties()
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-12T12:00:00Z",
            "payload": {"title": "Do it", "description": "desc", "reward_karma": 0},
        }
        error = process_post_bounty(delta, agents, bounties)
        assert error is not None
        assert "reward_karma" in error

    def test_invalid_reward_negative(self, tmp_state: Path) -> None:
        """Negative reward_karma is rejected."""
        from process_inbox import process_post_bounty
        agents = _make_agents(tmp_state, "agent-a")
        bounties = _empty_bounties()
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-12T12:00:00Z",
            "payload": {"title": "Do it", "description": "desc", "reward_karma": -5},
        }
        error = process_post_bounty(delta, agents, bounties)
        assert error is not None
        assert "reward_karma" in error

    def test_insufficient_karma(self, tmp_state: Path) -> None:
        """Agent with less karma than reward cannot post bounty."""
        from process_inbox import process_post_bounty
        agents = _make_agents(tmp_state, "agent-a", **{"agent-a": {"karma": 5}})
        bounties = _empty_bounties()
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-12T12:00:00Z",
            "payload": {"title": "Big bounty", "description": "desc", "reward_karma": 50},
        }
        error = process_post_bounty(delta, agents, bounties)
        assert error is not None
        assert "karma" in error.lower()

    def test_max_open_bounties_five_ok(self, tmp_state: Path) -> None:
        """An agent with 4 open bounties can post a 5th."""
        from process_inbox import process_post_bounty
        agents = _make_agents(tmp_state, "agent-a", **{"agent-a": {"karma": 500}})
        bounties = _empty_bounties()
        for i in range(4):
            _make_bounty(bounties, f"bounty-existing-{i}", "agent-a", reward=10)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-12T12:00:00Z",
            "payload": {"title": "Fifth bounty", "description": "desc", "reward_karma": 10},
        }
        error = process_post_bounty(delta, agents, bounties)
        assert error is None

    def test_max_open_bounties_sixth_rejected(self, tmp_state: Path) -> None:
        """An agent with 5 open bounties cannot post a 6th."""
        from process_inbox import process_post_bounty
        agents = _make_agents(tmp_state, "agent-a", **{"agent-a": {"karma": 500}})
        bounties = _empty_bounties()
        for i in range(5):
            _make_bounty(bounties, f"bounty-existing-{i}", "agent-a", reward=10)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-12T12:00:00Z",
            "payload": {"title": "Sixth bounty", "description": "desc", "reward_karma": 10},
        }
        error = process_post_bounty(delta, agents, bounties)
        assert error is not None
        assert "Max" in error or "max" in error

    def test_karma_escrowed(self, tmp_state: Path) -> None:
        """Posting a bounty deducts reward_karma from the agent."""
        from process_inbox import process_post_bounty
        agents = _make_agents(tmp_state, "agent-a", **{"agent-a": {"karma": 100}})
        bounties = _empty_bounties()
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-12T12:00:00Z",
            "payload": {"title": "Earn this", "description": "desc", "reward_karma": 30},
        }
        process_post_bounty(delta, agents, bounties)
        assert agents["agents"]["agent-a"]["karma"] == 70


# ---------------------------------------------------------------------------
# Unit tests — process_claim_bounty()
# ---------------------------------------------------------------------------

class TestClaimBountyUnit:
    def test_claim_succeeds(self, tmp_state: Path) -> None:
        """Happy path: claimer receives karma reward."""
        from process_inbox import process_claim_bounty
        agents = _make_agents(tmp_state, "agent-a", "agent-b")
        bounties = _empty_bounties()
        _make_bounty(bounties, "bounty-1", "agent-a", reward=10)
        notifications = _empty_notifications()
        delta = {
            "agent_id": "agent-b",
            "timestamp": "2026-02-15T12:00:00Z",
            "payload": {"bounty_id": "bounty-1"},
        }
        error = process_claim_bounty(delta, agents, bounties, notifications)
        assert error is None
        assert bounties["bounties"]["bounty-1"]["status"] == "claimed"
        assert bounties["bounties"]["bounty-1"]["claimed_by"] == "agent-b"
        assert agents["agents"]["agent-b"]["karma"] == 110

    def test_bounty_not_found(self, tmp_state: Path) -> None:
        """Claiming a non-existent bounty returns error."""
        from process_inbox import process_claim_bounty
        agents = _make_agents(tmp_state, "agent-b")
        bounties = _empty_bounties()
        notifications = _empty_notifications()
        delta = {
            "agent_id": "agent-b",
            "timestamp": "2026-02-15T12:00:00Z",
            "payload": {"bounty_id": "bounty-999"},
        }
        error = process_claim_bounty(delta, agents, bounties, notifications)
        assert error is not None
        assert "not found" in error

    def test_not_open(self, tmp_state: Path) -> None:
        """Claiming an already-claimed bounty returns error."""
        from process_inbox import process_claim_bounty
        agents = _make_agents(tmp_state, "agent-a", "agent-b")
        bounties = _empty_bounties()
        _make_bounty(bounties, "bounty-1", "agent-a", reward=10, status="claimed")
        notifications = _empty_notifications()
        delta = {
            "agent_id": "agent-b",
            "timestamp": "2026-02-15T12:00:00Z",
            "payload": {"bounty_id": "bounty-1"},
        }
        error = process_claim_bounty(delta, agents, bounties, notifications)
        assert error is not None
        assert "not open" in error

    def test_self_claim_blocked(self, tmp_state: Path) -> None:
        """Bounty poster cannot claim their own bounty."""
        from process_inbox import process_claim_bounty
        agents = _make_agents(tmp_state, "agent-a")
        bounties = _empty_bounties()
        _make_bounty(bounties, "bounty-1", "agent-a", reward=10)
        notifications = _empty_notifications()
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-15T12:00:00Z",
            "payload": {"bounty_id": "bounty-1"},
        }
        error = process_claim_bounty(delta, agents, bounties, notifications)
        assert error is not None
        assert "own" in error.lower()

    def test_expired_bounty_refunds_poster(self, tmp_state: Path) -> None:
        """Claiming an expired bounty refunds karma to the poster."""
        from process_inbox import process_claim_bounty
        agents = _make_agents(tmp_state, "agent-a", "agent-b",
                              **{"agent-a": {"karma": 50}})
        bounties = _empty_bounties()
        _make_bounty(bounties, "bounty-1", "agent-a", reward=10)
        # Override expires_at to be in the past
        bounties["bounties"]["bounty-1"]["expires_at"] = "2026-02-01T00:00:00Z"
        notifications = _empty_notifications()
        delta = {
            "agent_id": "agent-b",
            "timestamp": "2026-02-15T12:00:00Z",
            "payload": {"bounty_id": "bounty-1"},
        }
        error = process_claim_bounty(delta, agents, bounties, notifications)
        assert error is not None
        assert "expired" in error
        assert bounties["bounties"]["bounty-1"]["status"] == "expired"
        # Poster gets refund
        assert agents["agents"]["agent-a"]["karma"] == 60

    def test_notification_sent_to_poster(self, tmp_state: Path) -> None:
        """A successful claim sends a notification to the bounty poster."""
        from process_inbox import process_claim_bounty
        agents = _make_agents(tmp_state, "agent-a", "agent-b")
        bounties = _empty_bounties()
        _make_bounty(bounties, "bounty-1", "agent-a", reward=10)
        notifications = _empty_notifications()
        delta = {
            "agent_id": "agent-b",
            "timestamp": "2026-02-15T12:00:00Z",
            "payload": {"bounty_id": "bounty-1"},
        }
        process_claim_bounty(delta, agents, bounties, notifications)
        assert len(notifications["notifications"]) == 1
        notif = notifications["notifications"][0]
        assert notif["agent_id"] == "agent-a"
        assert notif["type"] == "bounty_claimed"
        assert notif["from_agent"] == "agent-b"


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

class TestBountyIntegration:
    def test_post_pipeline(self, tmp_state: Path) -> None:
        """End-to-end: write delta, run process_inbox, verify bounties state."""
        _make_agents(tmp_state, "agent-a", **{"agent-a": {"karma": 100}})

        write_delta(
            tmp_state / "inbox", "agent-a", "post_bounty",
            {"title": "Integration bounty", "description": "Do the thing", "reward_karma": 25},
        )

        result = run_inbox(tmp_state)
        assert result.returncode == 0, f"process_inbox failed: {result.stderr}"

        bounties = json.loads((tmp_state / "archive" / "bounties.json").read_text())
        assert bounties["_meta"]["count"] == 1
        bounty = list(bounties["bounties"].values())[0]
        assert bounty["posted_by"] == "agent-a"
        assert bounty["status"] == "open"
        assert bounty["reward_karma"] == 25

        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["agent-a"]["karma"] == 75

    def test_claim_pipeline(self, tmp_state: Path) -> None:
        """End-to-end: post then claim a bounty, verify karma transfer."""
        _make_agents(tmp_state, "agent-a", "agent-b",
                     **{"agent-a": {"karma": 100}, "agent-b": {"karma": 50}})

        # Seed a bounty directly in state
        bounties = {"bounties": {}, "_meta": {"count": 0, "last_updated": "2026-02-12T00:00:00Z"}}
        _make_bounty(bounties, "bounty-1", "agent-a", reward=20)
        (tmp_state / "archive" / "bounties.json").write_text(json.dumps(bounties, indent=2))

        write_delta(
            tmp_state / "inbox", "agent-b", "claim_bounty",
            {"bounty_id": "bounty-1"},
            timestamp="2026-02-15T12:00:00Z",
        )

        result = run_inbox(tmp_state)
        assert result.returncode == 0, f"process_inbox failed: {result.stderr}"

        bounties_out = json.loads((tmp_state / "archive" / "bounties.json").read_text())
        assert bounties_out["bounties"]["bounty-1"]["status"] == "claimed"
        assert bounties_out["bounties"]["bounty-1"]["claimed_by"] == "agent-b"

        agents_out = json.loads((tmp_state / "agents.json").read_text())
        assert agents_out["agents"]["agent-b"]["karma"] == 70
