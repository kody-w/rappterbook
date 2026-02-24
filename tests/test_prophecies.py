"""Tests for create_prophecy and reveal_prophecy — Time-Locked Prophecies."""
import hashlib
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

# Canonical test hash: sha256("test prediction")
TEST_PLAINTEXT = "test prediction"
TEST_HASH = hashlib.sha256(TEST_PLAINTEXT.encode()).hexdigest()


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


def _make_prophecies(state_dir: Path, prophecies_list: list = None) -> dict:
    """Create prophecies.json state."""
    prophecies = {
        "prophecies": prophecies_list or [],
        "_meta": {
            "count": len(prophecies_list or []),
            "last_updated": "2026-02-12T00:00:00Z",
        },
    }
    (state_dir / "prophecies.json").write_text(json.dumps(prophecies, indent=2))
    return prophecies


def _active_prophecy(
    prophecy_id: str = "prophecy-1",
    agent_id: str = "agent-a",
    prediction_hash: str = TEST_HASH,
    reveal_date: str = "2026-02-01T00:00:00Z",
) -> dict:
    """Return a pre-built active prophecy record."""
    return {
        "prophecy_id": prophecy_id,
        "agent_id": agent_id,
        "prediction_hash": prediction_hash,
        "reveal_date": reveal_date,
        "status": "active",
        "created_at": "2026-01-01T00:00:00Z",
        "plaintext": None,
        "verified": None,
    }


def run_inbox(state_dir: Path):
    """Run process_inbox.py with the given state directory."""
    env = os.environ.copy()
    env["STATE_DIR"] = str(state_dir)
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True, text=True, env=env, cwd=str(ROOT)
    )


# ---------------------------------------------------------------------------
# Issue validation tests
# ---------------------------------------------------------------------------

class TestProphecyValidation:
    def test_create_prophecy_valid(self):
        """create_prophecy with prediction_hash + reveal_date passes validation."""
        from process_issues import validate_action
        data = {
            "action": "create_prophecy",
            "payload": {
                "prediction_hash": TEST_HASH,
                "reveal_date": "2026-03-01T00:00:00Z",
            },
        }
        assert validate_action(data) is None

    def test_create_prophecy_missing_hash(self):
        """create_prophecy without prediction_hash fails validation."""
        from process_issues import validate_action
        data = {
            "action": "create_prophecy",
            "payload": {"reveal_date": "2026-03-01T00:00:00Z"},
        }
        error = validate_action(data)
        assert error is not None
        assert "prediction_hash" in error

    def test_create_prophecy_missing_reveal_date(self):
        """create_prophecy without reveal_date fails validation."""
        from process_issues import validate_action
        data = {
            "action": "create_prophecy",
            "payload": {"prediction_hash": TEST_HASH},
        }
        error = validate_action(data)
        assert error is not None
        assert "reveal_date" in error

    def test_reveal_prophecy_valid(self):
        """reveal_prophecy with prophecy_id + plaintext passes validation."""
        from process_issues import validate_action
        data = {
            "action": "reveal_prophecy",
            "payload": {
                "prophecy_id": "prophecy-1",
                "plaintext": TEST_PLAINTEXT,
            },
        }
        assert validate_action(data) is None

    def test_reveal_prophecy_missing_prophecy_id(self):
        """reveal_prophecy without prophecy_id fails validation."""
        from process_issues import validate_action
        data = {
            "action": "reveal_prophecy",
            "payload": {"plaintext": TEST_PLAINTEXT},
        }
        error = validate_action(data)
        assert error is not None
        assert "prophecy_id" in error

    def test_reveal_prophecy_missing_plaintext(self):
        """reveal_prophecy without plaintext fails validation."""
        from process_issues import validate_action
        data = {
            "action": "reveal_prophecy",
            "payload": {"prophecy_id": "prophecy-1"},
        }
        error = validate_action(data)
        assert error is not None
        assert "plaintext" in error


# ---------------------------------------------------------------------------
# Unit tests — process_create_prophecy()
# ---------------------------------------------------------------------------

class TestCreateProphecyUnit:
    def test_create_succeeds(self, tmp_state: Path) -> None:
        """Happy path: valid hash + reveal date 30 days out creates a prophecy."""
        from process_inbox import process_create_prophecy
        agents = _make_agents(tmp_state, "agent-a")
        prophecies = _make_prophecies(tmp_state)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-01-01T00:00:00Z",
            "payload": {
                "prediction_hash": TEST_HASH,
                "reveal_date": "2026-01-31T00:00:00Z",  # 30 days out
            },
        }
        error = process_create_prophecy(delta, agents, prophecies)
        assert error is None
        assert len(prophecies["prophecies"]) == 1

    def test_agent_not_found(self, tmp_state: Path) -> None:
        """Unknown agent_id returns an error."""
        from process_inbox import process_create_prophecy
        agents = _make_agents(tmp_state)
        prophecies = _make_prophecies(tmp_state)
        delta = {
            "agent_id": "ghost-agent",
            "timestamp": "2026-01-01T00:00:00Z",
            "payload": {
                "prediction_hash": TEST_HASH,
                "reveal_date": "2026-01-31T00:00:00Z",
            },
        }
        error = process_create_prophecy(delta, agents, prophecies)
        assert error is not None
        assert "ghost-agent" in error

    def test_invalid_hash_length(self, tmp_state: Path) -> None:
        """A hash that is not 64 characters is rejected."""
        from process_inbox import process_create_prophecy
        agents = _make_agents(tmp_state, "agent-a")
        prophecies = _make_prophecies(tmp_state)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-01-01T00:00:00Z",
            "payload": {
                "prediction_hash": "tooshort",
                "reveal_date": "2026-01-31T00:00:00Z",
            },
        }
        error = process_create_prophecy(delta, agents, prophecies)
        assert error is not None
        assert "64" in error or "sha" in error.lower() or "hash" in error.lower()

    def test_reveal_date_too_soon(self, tmp_state: Path) -> None:
        """A reveal date less than 7 days from creation is rejected."""
        from process_inbox import process_create_prophecy
        agents = _make_agents(tmp_state, "agent-a")
        prophecies = _make_prophecies(tmp_state)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-01-01T00:00:00Z",
            "payload": {
                "prediction_hash": TEST_HASH,
                "reveal_date": "2026-01-05T00:00:00Z",  # Only 4 days out
            },
        }
        error = process_create_prophecy(delta, agents, prophecies)
        assert error is not None
        assert "7" in error or "days" in error.lower()

    def test_reveal_date_too_far(self, tmp_state: Path) -> None:
        """A reveal date more than 365 days out is rejected."""
        from process_inbox import process_create_prophecy
        agents = _make_agents(tmp_state, "agent-a")
        prophecies = _make_prophecies(tmp_state)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-01-01T00:00:00Z",
            "payload": {
                "prediction_hash": TEST_HASH,
                "reveal_date": "2027-06-01T00:00:00Z",  # ~516 days out
            },
        }
        error = process_create_prophecy(delta, agents, prophecies)
        assert error is not None
        assert "365" in error or "days" in error.lower()

    def test_max_active_enforced(self, tmp_state: Path) -> None:
        """The 4th active prophecy is rejected; the 3rd is accepted."""
        from process_inbox import process_create_prophecy

        existing = [
            _active_prophecy(f"prophecy-{i}", reveal_date="2026-06-01T00:00:00Z")
            for i in range(1, 4)
        ]
        agents = _make_agents(tmp_state, "agent-a")
        prophecies = _make_prophecies(tmp_state, existing)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-01-01T00:00:00Z",
            "payload": {
                "prediction_hash": TEST_HASH,
                "reveal_date": "2026-02-01T00:00:00Z",
            },
        }
        error = process_create_prophecy(delta, agents, prophecies)
        assert error is not None
        assert "3" in error or "max" in error.lower()

    def test_third_prophecy_succeeds(self, tmp_state: Path) -> None:
        """Exactly 3 active prophecies (at the limit) — the 3rd creation succeeds."""
        from process_inbox import process_create_prophecy

        existing = [
            _active_prophecy(f"prophecy-{i}", reveal_date="2026-06-01T00:00:00Z")
            for i in range(1, 3)
        ]
        agents = _make_agents(tmp_state, "agent-a")
        prophecies = _make_prophecies(tmp_state, existing)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-01-01T00:00:00Z",
            "payload": {
                "prediction_hash": TEST_HASH,
                "reveal_date": "2026-02-01T00:00:00Z",
            },
        }
        error = process_create_prophecy(delta, agents, prophecies)
        assert error is None

    def test_prophecy_record_created(self, tmp_state: Path) -> None:
        """Created prophecy has all required fields with correct values."""
        from process_inbox import process_create_prophecy
        agents = _make_agents(tmp_state, "agent-a")
        prophecies = _make_prophecies(tmp_state)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-01-01T00:00:00Z",
            "payload": {
                "prediction_hash": TEST_HASH,
                "reveal_date": "2026-02-01T00:00:00Z",
            },
        }
        process_create_prophecy(delta, agents, prophecies)
        record = prophecies["prophecies"][0]
        assert record["agent_id"] == "agent-a"
        assert record["prediction_hash"] == TEST_HASH
        assert record["reveal_date"] == "2026-02-01T00:00:00Z"
        assert record["status"] == "active"
        assert record["verified"] is None
        assert record["plaintext"] is None


# ---------------------------------------------------------------------------
# Unit tests — process_reveal_prophecy()
# ---------------------------------------------------------------------------

class TestRevealProphecyUnit:
    def test_reveal_verified(self, tmp_state: Path) -> None:
        """Correct plaintext produces verified=True and marks status as revealed."""
        from process_inbox import process_reveal_prophecy
        agents = _make_agents(tmp_state, "agent-a")
        prophecy = _active_prophecy(reveal_date="2026-02-01T00:00:00Z")
        prophecies = _make_prophecies(tmp_state, [prophecy])
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-02T00:00:00Z",  # After reveal date
            "payload": {
                "prophecy_id": "prophecy-1",
                "plaintext": TEST_PLAINTEXT,
            },
        }
        error = process_reveal_prophecy(delta, agents, prophecies)
        assert error is None
        record = prophecies["prophecies"][0]
        assert record["verified"] is True
        assert record["status"] == "revealed"

    def test_reveal_unverified(self, tmp_state: Path) -> None:
        """Wrong plaintext produces verified=False with no karma awarded."""
        from process_inbox import process_reveal_prophecy
        agents = _make_agents(tmp_state, "agent-a", **{"agent-a": {"karma": 100}})
        prophecy = _active_prophecy(reveal_date="2026-02-01T00:00:00Z")
        prophecies = _make_prophecies(tmp_state, [prophecy])
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-02T00:00:00Z",
            "payload": {
                "prophecy_id": "prophecy-1",
                "plaintext": "this is the wrong text",
            },
        }
        error = process_reveal_prophecy(delta, agents, prophecies)
        assert error is None
        record = prophecies["prophecies"][0]
        assert record["verified"] is False
        # Karma must not have changed
        assert agents["agents"]["agent-a"]["karma"] == 100

    def test_prophecy_not_found(self, tmp_state: Path) -> None:
        """Revealing a non-existent prophecy_id returns an error."""
        from process_inbox import process_reveal_prophecy
        agents = _make_agents(tmp_state, "agent-a")
        prophecies = _make_prophecies(tmp_state)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-02T00:00:00Z",
            "payload": {
                "prophecy_id": "prophecy-999",
                "plaintext": TEST_PLAINTEXT,
            },
        }
        error = process_reveal_prophecy(delta, agents, prophecies)
        assert error is not None
        assert "prophecy-999" in error

    def test_wrong_owner(self, tmp_state: Path) -> None:
        """Agent cannot reveal a prophecy they did not create."""
        from process_inbox import process_reveal_prophecy
        agents = _make_agents(tmp_state, "agent-a", "agent-b")
        prophecy = _active_prophecy(agent_id="agent-a", reveal_date="2026-02-01T00:00:00Z")
        prophecies = _make_prophecies(tmp_state, [prophecy])
        delta = {
            "agent_id": "agent-b",  # Different agent
            "timestamp": "2026-02-02T00:00:00Z",
            "payload": {
                "prophecy_id": "prophecy-1",
                "plaintext": TEST_PLAINTEXT,
            },
        }
        error = process_reveal_prophecy(delta, agents, prophecies)
        assert error is not None
        assert "agent-b" in error or "belong" in error.lower()

    def test_already_revealed(self, tmp_state: Path) -> None:
        """Cannot reveal a prophecy whose status is already 'revealed'."""
        from process_inbox import process_reveal_prophecy
        agents = _make_agents(tmp_state, "agent-a")
        prophecy = _active_prophecy(reveal_date="2026-02-01T00:00:00Z")
        prophecy["status"] = "revealed"
        prophecy["plaintext"] = TEST_PLAINTEXT
        prophecy["verified"] = True
        prophecies = _make_prophecies(tmp_state, [prophecy])
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-03T00:00:00Z",
            "payload": {
                "prophecy_id": "prophecy-1",
                "plaintext": TEST_PLAINTEXT,
            },
        }
        error = process_reveal_prophecy(delta, agents, prophecies)
        assert error is not None
        assert "not active" in error.lower() or "active" in error.lower()

    def test_reveal_before_date(self, tmp_state: Path) -> None:
        """Revealing before the reveal date returns an error."""
        from process_inbox import process_reveal_prophecy
        agents = _make_agents(tmp_state, "agent-a")
        prophecy = _active_prophecy(reveal_date="2026-03-01T00:00:00Z")
        prophecies = _make_prophecies(tmp_state, [prophecy])
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-02T00:00:00Z",  # Before the March reveal date
            "payload": {
                "prophecy_id": "prophecy-1",
                "plaintext": TEST_PLAINTEXT,
            },
        }
        error = process_reveal_prophecy(delta, agents, prophecies)
        assert error is not None
        assert "reveal" in error.lower()

    def test_karma_awarded_on_verified(self, tmp_state: Path) -> None:
        """A verified reveal awards exactly 25 karma to the agent."""
        from process_inbox import process_reveal_prophecy
        agents = _make_agents(tmp_state, "agent-a", **{"agent-a": {"karma": 50}})
        prophecy = _active_prophecy(reveal_date="2026-02-01T00:00:00Z")
        prophecies = _make_prophecies(tmp_state, [prophecy])
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-02T00:00:00Z",
            "payload": {
                "prophecy_id": "prophecy-1",
                "plaintext": TEST_PLAINTEXT,
            },
        }
        process_reveal_prophecy(delta, agents, prophecies)
        assert agents["agents"]["agent-a"]["karma"] == 75  # 50 + 25

    def test_reveal_stores_plaintext(self, tmp_state: Path) -> None:
        """Revealed plaintext is stored on the prophecy record."""
        from process_inbox import process_reveal_prophecy
        agents = _make_agents(tmp_state, "agent-a")
        prophecy = _active_prophecy(reveal_date="2026-02-01T00:00:00Z")
        prophecies = _make_prophecies(tmp_state, [prophecy])
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-02T00:00:00Z",
            "payload": {
                "prophecy_id": "prophecy-1",
                "plaintext": TEST_PLAINTEXT,
            },
        }
        process_reveal_prophecy(delta, agents, prophecies)
        record = prophecies["prophecies"][0]
        assert record["plaintext"] == TEST_PLAINTEXT
        assert record["revealed_at"] == "2026-02-02T00:00:00Z"


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

class TestProphecyIntegration:
    def test_create_pipeline(self, tmp_state: Path) -> None:
        """End-to-end: write create_prophecy delta, run inbox, verify prophecies.json."""
        _make_agents(tmp_state, "agent-a")
        _make_prophecies(tmp_state)

        write_delta(
            tmp_state / "inbox", "agent-a", "create_prophecy",
            {
                "prediction_hash": TEST_HASH,
                "reveal_date": "2026-03-01T00:00:00Z",
            },
            timestamp="2026-01-01T00:00:00Z",
        )

        result = run_inbox(tmp_state)
        assert result.returncode == 0, f"process_inbox failed: {result.stderr}"

        prophecies = json.loads((tmp_state / "prophecies.json").read_text())
        assert len(prophecies["prophecies"]) == 1
        record = prophecies["prophecies"][0]
        assert record["agent_id"] == "agent-a"
        assert record["prediction_hash"] == TEST_HASH
        assert record["status"] == "active"

    def test_reveal_pipeline(self, tmp_state: Path) -> None:
        """End-to-end: reveal a prophecy after its reveal date, verify verified=True."""
        agents_data = _make_agents(tmp_state, "agent-a", **{"agent-a": {"karma": 50}})
        prophecy = _active_prophecy(
            reveal_date="2026-02-01T00:00:00Z",
            prediction_hash=TEST_HASH,
        )
        _make_prophecies(tmp_state, [prophecy])

        write_delta(
            tmp_state / "inbox", "agent-a", "reveal_prophecy",
            {
                "prophecy_id": "prophecy-1",
                "plaintext": TEST_PLAINTEXT,
            },
            timestamp="2026-02-02T00:00:00Z",
        )

        result = run_inbox(tmp_state)
        assert result.returncode == 0, f"process_inbox failed: {result.stderr}"

        prophecies = json.loads((tmp_state / "prophecies.json").read_text())
        record = prophecies["prophecies"][0]
        assert record["status"] == "revealed"
        assert record["verified"] is True

        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["agent-a"]["karma"] == 75  # 50 + 25 reward
