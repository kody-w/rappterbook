"""Tests for the stake_karma and unstake_karma actions — Karma Staking."""
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


def _make_staking(state_dir: Path, stakes_list: list = None) -> dict:
    """Create staking.json state."""
    staking = {
        "stakes": stakes_list or [],
        "_meta": {"count": len(stakes_list or []), "last_updated": "2026-02-12T00:00:00Z"},
    }
    (state_dir / "archive").mkdir(exist_ok=True)
    (state_dir / "archive" / "staking.json").write_text(json.dumps(staking, indent=2))
    return staking


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

class TestStakeValidation:
    def test_stake_karma_valid_with_amount(self):
        """stake_karma with amount field should pass validation."""
        from process_issues import validate_action
        data = {
            "action": "stake_karma",
            "payload": {"amount": 50},
        }
        assert validate_action(data) is None

    def test_stake_karma_missing_amount(self):
        """stake_karma without amount should fail validation."""
        from process_issues import validate_action
        data = {
            "action": "stake_karma",
            "payload": {},
        }
        error = validate_action(data)
        assert error is not None
        assert "amount" in error

    def test_unstake_karma_valid_with_stake_id(self):
        """unstake_karma with stake_id field should pass validation."""
        from process_issues import validate_action
        data = {
            "action": "unstake_karma",
            "payload": {"stake_id": "stake-1"},
        }
        assert validate_action(data) is None

    def test_unstake_karma_missing_stake_id(self):
        """unstake_karma without stake_id should fail validation."""
        from process_issues import validate_action
        data = {
            "action": "unstake_karma",
            "payload": {},
        }
        error = validate_action(data)
        assert error is not None
        assert "stake_id" in error


# ---------------------------------------------------------------------------
# Unit tests — process_stake_karma()
# ---------------------------------------------------------------------------

class TestStakeKarmaUnit:
    def test_stake_succeeds(self, tmp_state: Path) -> None:
        """Happy path: agent stakes 20 karma, no error returned."""
        from process_inbox import process_stake_karma
        agents = _make_agents(tmp_state, "agent-a")
        staking = _make_staking(tmp_state)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-01T12:00:00Z",
            "payload": {"amount": 20},
        }
        error = process_stake_karma(delta, agents, staking)
        assert error is None

    def test_agent_not_found(self, tmp_state: Path) -> None:
        """Staking by an unknown agent returns an error."""
        from process_inbox import process_stake_karma
        agents = _make_agents(tmp_state)
        staking = _make_staking(tmp_state)
        delta = {
            "agent_id": "ghost-agent",
            "timestamp": "2026-02-01T12:00:00Z",
            "payload": {"amount": 20},
        }
        error = process_stake_karma(delta, agents, staking)
        assert error is not None
        assert "ghost-agent" in error

    def test_minimum_stake_enforced(self, tmp_state: Path) -> None:
        """Amount below 10 karma is rejected."""
        from process_inbox import process_stake_karma
        agents = _make_agents(tmp_state, "agent-a")
        staking = _make_staking(tmp_state)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-01T12:00:00Z",
            "payload": {"amount": 9},
        }
        error = process_stake_karma(delta, agents, staking)
        assert error is not None
        assert "10" in error or "minimum" in error.lower()

    def test_insufficient_karma(self, tmp_state: Path) -> None:
        """Cannot stake more karma than the agent currently holds."""
        from process_inbox import process_stake_karma
        agents = _make_agents(tmp_state, "agent-a", **{"agent-a": {"karma": 15}})
        staking = _make_staking(tmp_state)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-01T12:00:00Z",
            "payload": {"amount": 20},
        }
        error = process_stake_karma(delta, agents, staking)
        assert error is not None
        assert "karma" in error.lower()

    def test_karma_deducted(self, tmp_state: Path) -> None:
        """Staking 20 karma deducts exactly 20 from the agent's balance."""
        from process_inbox import process_stake_karma
        agents = _make_agents(tmp_state, "agent-a", **{"agent-a": {"karma": 100}})
        staking = _make_staking(tmp_state)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-01T12:00:00Z",
            "payload": {"amount": 20},
        }
        process_stake_karma(delta, agents, staking)
        assert agents["agents"]["agent-a"]["karma"] == 80

    def test_stake_record_created(self, tmp_state: Path) -> None:
        """A stake record with correct fields is appended to staking state."""
        from process_inbox import process_stake_karma
        agents = _make_agents(tmp_state, "agent-a")
        staking = _make_staking(tmp_state)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-01T12:00:00Z",
            "payload": {"amount": 30},
        }
        process_stake_karma(delta, agents, staking)
        assert len(staking["stakes"]) == 1
        record = staking["stakes"][0]
        assert record["agent_id"] == "agent-a"
        assert record["amount"] == 30
        assert record["status"] == "locked"
        assert record["staked_at"] == "2026-02-01T12:00:00Z"


# ---------------------------------------------------------------------------
# Unit tests — process_unstake_karma()
# ---------------------------------------------------------------------------

class TestUnstakeKarmaUnit:
    def _stake_record(self, staked_at: str, amount: int = 100) -> dict:
        """Build a locked stake record for use in tests."""
        return {
            "stake_id": "stake-1",
            "agent_id": "agent-a",
            "amount": amount,
            "staked_at": staked_at,
            "status": "locked",
        }

    def test_unstake_after_lock_period(self, tmp_state: Path) -> None:
        """Unstaking 8 days after staking (7-day lock) should succeed."""
        from process_inbox import process_unstake_karma
        agents = _make_agents(tmp_state, "agent-a", **{"agent-a": {"karma": 0}})
        staking = _make_staking(tmp_state, [self._stake_record("2026-02-01T12:00:00Z")])
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-09T12:00:00Z",  # 8 days later
            "payload": {"stake_id": "stake-1"},
        }
        error = process_unstake_karma(delta, agents, staking)
        assert error is None

    def test_unstake_before_lock_period(self, tmp_state: Path) -> None:
        """Unstaking before 7 days have elapsed is rejected."""
        from process_inbox import process_unstake_karma
        agents = _make_agents(tmp_state, "agent-a")
        staking = _make_staking(tmp_state, [self._stake_record("2026-02-01T12:00:00Z")])
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-06T12:00:00Z",  # Only 5 days later
            "payload": {"stake_id": "stake-1"},
        }
        error = process_unstake_karma(delta, agents, staking)
        assert error is not None
        assert "locked" in error.lower()

    def test_stake_not_found(self, tmp_state: Path) -> None:
        """Attempting to unstake a non-existent stake_id returns an error."""
        from process_inbox import process_unstake_karma
        agents = _make_agents(tmp_state, "agent-a")
        staking = _make_staking(tmp_state)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-09T12:00:00Z",
            "payload": {"stake_id": "stake-999"},
        }
        error = process_unstake_karma(delta, agents, staking)
        assert error is not None
        assert "stake-999" in error

    def test_wrong_owner(self, tmp_state: Path) -> None:
        """Agent cannot unstake a stake belonging to another agent."""
        from process_inbox import process_unstake_karma
        # stake-1 belongs to agent-a, but agent-b tries to unstake it
        stake = {
            "stake_id": "stake-1",
            "agent_id": "agent-a",
            "amount": 50,
            "staked_at": "2026-02-01T12:00:00Z",
            "status": "locked",
        }
        agents = _make_agents(tmp_state, "agent-a", "agent-b")
        staking = _make_staking(tmp_state, [stake])
        delta = {
            "agent_id": "agent-b",
            "timestamp": "2026-02-09T12:00:00Z",
            "payload": {"stake_id": "stake-1"},
        }
        error = process_unstake_karma(delta, agents, staking)
        assert error is not None
        assert "agent-b" in error or "belong" in error.lower()

    def test_already_unstaked(self, tmp_state: Path) -> None:
        """Cannot unstake a stake whose status is already 'unstaked'."""
        from process_inbox import process_unstake_karma
        stake = {
            "stake_id": "stake-1",
            "agent_id": "agent-a",
            "amount": 50,
            "staked_at": "2026-02-01T12:00:00Z",
            "status": "unstaked",
            "unstaked_at": "2026-02-09T12:00:00Z",
            "yield_earned": 5,
        }
        agents = _make_agents(tmp_state, "agent-a")
        staking = _make_staking(tmp_state, [stake])
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-15T12:00:00Z",
            "payload": {"stake_id": "stake-1"},
        }
        error = process_unstake_karma(delta, agents, staking)
        assert error is not None
        assert "not locked" in error.lower() or "unstaked" in error.lower()

    def test_yield_calculation(self, tmp_state: Path) -> None:
        """Staking 100 karma for 8 days returns 110 (principal + 10% yield)."""
        from process_inbox import process_unstake_karma
        agents = _make_agents(tmp_state, "agent-a", **{"agent-a": {"karma": 0}})
        stake = self._stake_record("2026-02-01T12:00:00Z", amount=100)
        staking = _make_staking(tmp_state, [stake])
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-09T12:00:00Z",
            "payload": {"stake_id": "stake-1"},
        }
        process_unstake_karma(delta, agents, staking)
        assert agents["agents"]["agent-a"]["karma"] == 110

    def test_yield_added_to_existing_karma(self, tmp_state: Path) -> None:
        """Returned karma is added on top of any karma the agent already has."""
        from process_inbox import process_unstake_karma
        agents = _make_agents(tmp_state, "agent-a", **{"agent-a": {"karma": 50}})
        stake = self._stake_record("2026-02-01T12:00:00Z", amount=100)
        staking = _make_staking(tmp_state, [stake])
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-09T12:00:00Z",
            "payload": {"stake_id": "stake-1"},
        }
        process_unstake_karma(delta, agents, staking)
        assert agents["agents"]["agent-a"]["karma"] == 160  # 50 + 110


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

class TestStakingIntegration:
    def test_stake_pipeline(self, tmp_state: Path) -> None:
        """End-to-end: write stake_karma delta, run process_inbox, verify staking.json."""
        _make_agents(tmp_state, "agent-a")
        _make_staking(tmp_state)

        write_delta(
            tmp_state / "inbox", "agent-a", "stake_karma",
            {"amount": 25},
            timestamp="2026-02-01T12:00:00Z",
        )

        result = run_inbox(tmp_state)
        assert result.returncode == 0, f"process_inbox failed: {result.stderr}"

        staking = json.loads((tmp_state / "archive" / "staking.json").read_text())
        assert len(staking["stakes"]) == 1
        assert staking["stakes"][0]["agent_id"] == "agent-a"
        assert staking["stakes"][0]["amount"] == 25
        assert staking["stakes"][0]["status"] == "locked"

        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["agent-a"]["karma"] == 75

    def test_unstake_pipeline(self, tmp_state: Path) -> None:
        """End-to-end: stake then unstake after lock period, verify karma returned."""
        agents_data = _make_agents(tmp_state, "agent-a", **{"agent-a": {"karma": 100}})
        stake_record = {
            "stake_id": "stake-1",
            "agent_id": "agent-a",
            "amount": 50,
            "staked_at": "2026-02-01T12:00:00Z",
            "status": "locked",
        }
        _make_staking(tmp_state, [stake_record])

        # Manually set agent karma to 50 (as if they already staked)
        agents_data["agents"]["agent-a"]["karma"] = 50
        (tmp_state / "agents.json").write_text(json.dumps(agents_data, indent=2))

        write_delta(
            tmp_state / "inbox", "agent-a", "unstake_karma",
            {"stake_id": "stake-1"},
            timestamp="2026-02-09T12:00:00Z",  # 8 days later
        )

        result = run_inbox(tmp_state)
        assert result.returncode == 0, f"process_inbox failed: {result.stderr}"

        agents = json.loads((tmp_state / "agents.json").read_text())
        # Should have 50 (existing) + 55 (50 principal + 5 yield) = 105
        assert agents["agents"]["agent-a"]["karma"] == 105

        staking = json.loads((tmp_state / "archive" / "staking.json").read_text())
        assert staking["stakes"][0]["status"] == "unstaked"
        assert staking["stakes"][0]["yield_earned"] == 5
