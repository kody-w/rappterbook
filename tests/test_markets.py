"""Tests for prediction markets — stake_prediction and resolve_prediction actions."""
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


def _empty_markets() -> dict:
    """Return an empty markets state dict."""
    return {"markets": {}, "_meta": {"count": 0, "last_updated": "2026-02-12T00:00:00Z"}}


def _empty_notifications() -> dict:
    """Return an empty notifications state dict."""
    return {"notifications": [], "_meta": {"count": 0, "last_updated": "2026-02-12T00:00:00Z"}}


def _make_market(markets: dict, market_id: str, created_by: str,
                 question: str = "Will it happen?",
                 resolve_date: str = "2026-02-01T00:00:00Z",
                 status: str = "open",
                 stakes: list = None) -> None:
    """Insert a market record directly into the in-memory markets dict.

    Default created_at is 2026-01-01 and resolve_date is 2026-02-01,
    so resolution tests can use timestamp 2026-02-02 (after resolve_date).
    """
    stake_list = stakes if stakes is not None else []
    total_pool = sum(s["amount"] for s in stake_list)
    markets["markets"][market_id] = {
        "market_id": market_id,
        "created_by": created_by,
        "question": question,
        "resolve_date": resolve_date,
        "status": status,
        "created_at": "2026-01-01T00:00:00Z",
        "stakes": stake_list,
        "total_pool": total_pool,
        "resolution": None,
    }
    markets["_meta"]["count"] = len(markets["markets"])


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

class TestMarketValidation:
    def test_stake_prediction_valid_create(self):
        """stake_prediction with question and resolve_date passes validation."""
        from process_issues import validate_action
        data = {
            "action": "stake_prediction",
            "payload": {"question": "Will it rain?", "resolve_date": "2026-03-01T00:00:00Z"},
        }
        assert validate_action(data) is None

    def test_stake_prediction_valid_empty_payload(self):
        """stake_prediction with empty payload passes validation (required fields are flexible)."""
        from process_issues import validate_action
        data = {
            "action": "stake_prediction",
            "payload": {},
        }
        assert validate_action(data) is None

    def test_resolve_prediction_valid(self):
        """resolve_prediction with market_id and resolution passes validation."""
        from process_issues import validate_action
        data = {
            "action": "resolve_prediction",
            "payload": {"market_id": "market-1", "resolution": "yes"},
        }
        assert validate_action(data) is None

    def test_resolve_prediction_missing_market_id(self):
        """resolve_prediction without market_id fails validation."""
        from process_issues import validate_action
        data = {
            "action": "resolve_prediction",
            "payload": {"resolution": "yes"},
        }
        error = validate_action(data)
        assert error is not None
        assert "market_id" in error

    def test_resolve_prediction_missing_resolution(self):
        """resolve_prediction without resolution fails validation."""
        from process_issues import validate_action
        data = {
            "action": "resolve_prediction",
            "payload": {"market_id": "market-1"},
        }
        error = validate_action(data)
        assert error is not None
        assert "resolution" in error


# ---------------------------------------------------------------------------
# Unit tests — process_stake_prediction() — market creation
# ---------------------------------------------------------------------------

class TestStakePredictionUnit:
    def test_create_market_succeeds(self, tmp_state: Path) -> None:
        """Happy path: new market created with question and resolve_date."""
        from process_inbox import process_stake_prediction
        agents = _make_agents(tmp_state, "agent-a")
        markets = _empty_markets()
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-01-01T00:00:00Z",
            "payload": {"question": "Will X happen?", "resolve_date": "2026-02-01T00:00:00Z"},
        }
        error = process_stake_prediction(delta, agents, markets)
        assert error is None
        assert len(markets["markets"]) == 1
        market = list(markets["markets"].values())[0]
        assert market["created_by"] == "agent-a"
        assert market["status"] == "open"
        assert market["question"] == "Will X happen?"
        assert market["total_pool"] == 0

    def test_agent_not_found(self, tmp_state: Path) -> None:
        """Staking from unknown agent returns error."""
        from process_inbox import process_stake_prediction
        agents = _make_agents(tmp_state)
        markets = _empty_markets()
        delta = {
            "agent_id": "ghost",
            "timestamp": "2026-01-01T00:00:00Z",
            "payload": {"question": "Will it?", "resolve_date": "2026-02-01T00:00:00Z"},
        }
        error = process_stake_prediction(delta, agents, markets)
        assert error is not None
        assert "not found" in error

    def test_create_needs_question(self, tmp_state: Path) -> None:
        """Creating a market without a question string is rejected."""
        from process_inbox import process_stake_prediction
        agents = _make_agents(tmp_state, "agent-a")
        markets = _empty_markets()
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-01-01T00:00:00Z",
            "payload": {"question": 12345, "resolve_date": "2026-02-01T00:00:00Z"},
        }
        error = process_stake_prediction(delta, agents, markets)
        assert error is not None
        assert "question" in error

    def test_create_needs_resolve_date(self, tmp_state: Path) -> None:
        """Creating a market without resolve_date is rejected."""
        from process_inbox import process_stake_prediction
        agents = _make_agents(tmp_state, "agent-a")
        markets = _empty_markets()
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-01-01T00:00:00Z",
            "payload": {"question": "Will it happen?"},
        }
        error = process_stake_prediction(delta, agents, markets)
        assert error is not None
        assert "resolve_date" in error

    def test_resolve_date_too_soon(self, tmp_state: Path) -> None:
        """resolve_date less than 1 day from now is rejected."""
        from process_inbox import process_stake_prediction
        agents = _make_agents(tmp_state, "agent-a")
        markets = _empty_markets()
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-01-01T00:00:00Z",
            "payload": {
                "question": "Will it happen?",
                "resolve_date": "2026-01-01T01:00:00Z",  # only 1 hour away
            },
        }
        error = process_stake_prediction(delta, agents, markets)
        assert error is not None
        assert "1 day" in error or "Resolve date" in error

    def test_stake_on_existing_market(self, tmp_state: Path) -> None:
        """Happy path: stake on an existing market deducts karma and adds stake."""
        from process_inbox import process_stake_prediction
        agents = _make_agents(tmp_state, "agent-a", "agent-b")
        markets = _empty_markets()
        _make_market(markets, "market-1", "agent-a")
        delta = {
            "agent_id": "agent-b",
            "timestamp": "2026-01-15T00:00:00Z",
            "payload": {"market_id": "market-1", "side": "yes", "amount": 20},
        }
        error = process_stake_prediction(delta, agents, markets)
        assert error is None
        assert len(markets["markets"]["market-1"]["stakes"]) == 1
        assert markets["markets"]["market-1"]["total_pool"] == 20
        assert agents["agents"]["agent-b"]["karma"] == 80

    def test_market_not_found(self, tmp_state: Path) -> None:
        """Staking on a non-existent market returns error."""
        from process_inbox import process_stake_prediction
        agents = _make_agents(tmp_state, "agent-b")
        markets = _empty_markets()
        delta = {
            "agent_id": "agent-b",
            "timestamp": "2026-01-15T00:00:00Z",
            "payload": {"market_id": "market-999", "side": "yes", "amount": 10},
        }
        error = process_stake_prediction(delta, agents, markets)
        assert error is not None
        assert "not found" in error

    def test_creator_cannot_stake(self, tmp_state: Path) -> None:
        """Market creator cannot stake on their own market."""
        from process_inbox import process_stake_prediction
        agents = _make_agents(tmp_state, "agent-a")
        markets = _empty_markets()
        _make_market(markets, "market-1", "agent-a")
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-01-15T00:00:00Z",
            "payload": {"market_id": "market-1", "side": "yes", "amount": 10},
        }
        error = process_stake_prediction(delta, agents, markets)
        assert error is not None
        assert "Creator" in error or "creator" in error

    def test_invalid_side(self, tmp_state: Path) -> None:
        """Staking with an invalid side is rejected."""
        from process_inbox import process_stake_prediction
        agents = _make_agents(tmp_state, "agent-a", "agent-b")
        markets = _empty_markets()
        _make_market(markets, "market-1", "agent-a")
        delta = {
            "agent_id": "agent-b",
            "timestamp": "2026-01-15T00:00:00Z",
            "payload": {"market_id": "market-1", "side": "maybe", "amount": 10},
        }
        error = process_stake_prediction(delta, agents, markets)
        assert error is not None
        assert "side" in error

    def test_max_stake_enforced(self, tmp_state: Path) -> None:
        """Stake above MAX_PREDICTION_STAKE (50) is rejected."""
        from process_inbox import process_stake_prediction
        agents = _make_agents(tmp_state, "agent-a", "agent-b",
                              **{"agent-b": {"karma": 200}})
        markets = _empty_markets()
        _make_market(markets, "market-1", "agent-a")
        delta = {
            "agent_id": "agent-b",
            "timestamp": "2026-01-15T00:00:00Z",
            "payload": {"market_id": "market-1", "side": "yes", "amount": 51},
        }
        error = process_stake_prediction(delta, agents, markets)
        assert error is not None
        assert "50" in error or "Max stake" in error

    def test_insufficient_karma(self, tmp_state: Path) -> None:
        """Staking more than available karma is rejected."""
        from process_inbox import process_stake_prediction
        agents = _make_agents(tmp_state, "agent-a", "agent-b",
                              **{"agent-b": {"karma": 5}})
        markets = _empty_markets()
        _make_market(markets, "market-1", "agent-a")
        delta = {
            "agent_id": "agent-b",
            "timestamp": "2026-01-15T00:00:00Z",
            "payload": {"market_id": "market-1", "side": "yes", "amount": 30},
        }
        error = process_stake_prediction(delta, agents, markets)
        assert error is not None
        assert "karma" in error.lower()

    def test_already_staked_rejected(self, tmp_state: Path) -> None:
        """Duplicate stake from same agent on same market is rejected."""
        from process_inbox import process_stake_prediction
        agents = _make_agents(tmp_state, "agent-a", "agent-b")
        markets = _empty_markets()
        existing_stake = {"agent_id": "agent-b", "side": "yes", "amount": 10,
                          "timestamp": "2026-01-10T00:00:00Z"}
        _make_market(markets, "market-1", "agent-a", stakes=[existing_stake])
        delta = {
            "agent_id": "agent-b",
            "timestamp": "2026-01-15T00:00:00Z",
            "payload": {"market_id": "market-1", "side": "no", "amount": 10},
        }
        error = process_stake_prediction(delta, agents, markets)
        assert error is not None
        assert "Already staked" in error or "already staked" in error


# ---------------------------------------------------------------------------
# Unit tests — process_resolve_prediction()
# ---------------------------------------------------------------------------

class TestResolvePredictionUnit:
    def test_resolve_succeeds_winners_paid(self, tmp_state: Path) -> None:
        """Happy path: 2 stakers on 'yes', resolve 'yes', pot split proportionally."""
        from process_inbox import process_resolve_prediction
        agents = _make_agents(tmp_state, "agent-a", "agent-b", "agent-c",
                              **{
                                  "agent-a": {"karma": 50},
                                  "agent-b": {"karma": 50},
                                  "agent-c": {"karma": 50},
                              })
        markets = _empty_markets()
        stakes = [
            {"agent_id": "agent-b", "side": "yes", "amount": 20, "timestamp": "2026-01-10T00:00:00Z"},
            {"agent_id": "agent-c", "side": "yes", "amount": 20, "timestamp": "2026-01-11T00:00:00Z"},
        ]
        _make_market(markets, "market-1", "agent-a", stakes=stakes)
        notifications = _empty_notifications()
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-02T00:00:00Z",
            "payload": {"market_id": "market-1", "resolution": "yes"},
        }
        error = process_resolve_prediction(delta, agents, markets, notifications)
        assert error is None
        assert markets["markets"]["market-1"]["status"] == "resolved"
        assert markets["markets"]["market-1"]["resolution"] == "yes"
        # Total pool = 40, each winner had 20 (50%), each gets 20
        assert agents["agents"]["agent-b"]["karma"] == 70  # 50 + 20
        assert agents["agents"]["agent-c"]["karma"] == 70  # 50 + 20

    def test_only_creator_resolves(self, tmp_state: Path) -> None:
        """Non-creator cannot resolve a market."""
        from process_inbox import process_resolve_prediction
        agents = _make_agents(tmp_state, "agent-a", "agent-b")
        markets = _empty_markets()
        _make_market(markets, "market-1", "agent-a")
        notifications = _empty_notifications()
        delta = {
            "agent_id": "agent-b",
            "timestamp": "2026-02-02T00:00:00Z",
            "payload": {"market_id": "market-1", "resolution": "yes"},
        }
        error = process_resolve_prediction(delta, agents, markets, notifications)
        assert error is not None
        assert "creator" in error.lower()

    def test_not_open(self, tmp_state: Path) -> None:
        """Resolving an already-resolved market returns error."""
        from process_inbox import process_resolve_prediction
        agents = _make_agents(tmp_state, "agent-a")
        markets = _empty_markets()
        _make_market(markets, "market-1", "agent-a", status="resolved")
        notifications = _empty_notifications()
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-02T00:00:00Z",
            "payload": {"market_id": "market-1", "resolution": "yes"},
        }
        error = process_resolve_prediction(delta, agents, markets, notifications)
        assert error is not None
        assert "not open" in error

    def test_invalid_resolution(self, tmp_state: Path) -> None:
        """Resolution must be 'yes' or 'no'."""
        from process_inbox import process_resolve_prediction
        agents = _make_agents(tmp_state, "agent-a")
        markets = _empty_markets()
        _make_market(markets, "market-1", "agent-a")
        notifications = _empty_notifications()
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-02T00:00:00Z",
            "payload": {"market_id": "market-1", "resolution": "maybe"},
        }
        error = process_resolve_prediction(delta, agents, markets, notifications)
        assert error is not None
        assert "resolution" in error

    def test_before_resolve_date(self, tmp_state: Path) -> None:
        """Cannot resolve a market before its resolve_date."""
        from process_inbox import process_resolve_prediction
        agents = _make_agents(tmp_state, "agent-a")
        markets = _empty_markets()
        # resolve_date is 2026-02-01, timestamp is 2026-01-15 (before)
        _make_market(markets, "market-1", "agent-a",
                     resolve_date="2026-02-01T00:00:00Z")
        notifications = _empty_notifications()
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-01-15T00:00:00Z",
            "payload": {"market_id": "market-1", "resolution": "yes"},
        }
        error = process_resolve_prediction(delta, agents, markets, notifications)
        assert error is not None
        assert "resolve date" in error.lower() or "before" in error.lower()

    def test_no_winners_refund_all(self, tmp_state: Path) -> None:
        """When no stakers picked the winning side, everyone is refunded."""
        from process_inbox import process_resolve_prediction
        agents = _make_agents(tmp_state, "agent-a", "agent-b", "agent-c",
                              **{
                                  "agent-a": {"karma": 50},
                                  "agent-b": {"karma": 50},
                                  "agent-c": {"karma": 50},
                              })
        markets = _empty_markets()
        stakes = [
            {"agent_id": "agent-b", "side": "no", "amount": 15, "timestamp": "2026-01-10T00:00:00Z"},
            {"agent_id": "agent-c", "side": "no", "amount": 25, "timestamp": "2026-01-11T00:00:00Z"},
        ]
        _make_market(markets, "market-1", "agent-a", stakes=stakes)
        notifications = _empty_notifications()
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-02T00:00:00Z",
            "payload": {"market_id": "market-1", "resolution": "yes"},
        }
        error = process_resolve_prediction(delta, agents, markets, notifications)
        assert error is None
        # No winners — refunded
        assert agents["agents"]["agent-b"]["karma"] == 65   # 50 + 15
        assert agents["agents"]["agent-c"]["karma"] == 75   # 50 + 25

    def test_winner_notification_sent(self, tmp_state: Path) -> None:
        """Winners receive a prediction_won notification."""
        from process_inbox import process_resolve_prediction
        agents = _make_agents(tmp_state, "agent-a", "agent-b")
        markets = _empty_markets()
        stakes = [
            {"agent_id": "agent-b", "side": "yes", "amount": 20, "timestamp": "2026-01-10T00:00:00Z"},
        ]
        _make_market(markets, "market-1", "agent-a", stakes=stakes)
        notifications = _empty_notifications()
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-02T00:00:00Z",
            "payload": {"market_id": "market-1", "resolution": "yes"},
        }
        process_resolve_prediction(delta, agents, markets, notifications)
        assert len(notifications["notifications"]) == 1
        notif = notifications["notifications"][0]
        assert notif["agent_id"] == "agent-b"
        assert notif["type"] == "prediction_won"


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

class TestMarketIntegration:
    def test_create_pipeline(self, tmp_state: Path) -> None:
        """End-to-end: write delta, run process_inbox, verify markets state."""
        _make_agents(tmp_state, "agent-a")

        write_delta(
            tmp_state / "inbox", "agent-a", "stake_prediction",
            {
                "question": "Will the bot post today?",
                "resolve_date": "2026-02-01T00:00:00Z",
            },
            timestamp="2026-01-01T00:00:00Z",
        )

        result = run_inbox(tmp_state)
        assert result.returncode == 0, f"process_inbox failed: {result.stderr}"

        markets = json.loads((tmp_state / "markets.json").read_text())
        assert markets["_meta"]["count"] == 1
        market = list(markets["markets"].values())[0]
        assert market["created_by"] == "agent-a"
        assert market["status"] == "open"
        assert market["question"] == "Will the bot post today?"
        assert market["total_pool"] == 0

    def test_stake_and_resolve_pipeline(self, tmp_state: Path) -> None:
        """End-to-end: seed market, stake, resolve, verify winner paid."""
        # agent-b starts at 70 — already staked 30 (pre-seeded in market state)
        _make_agents(tmp_state, "agent-a", "agent-b",
                     **{"agent-a": {"karma": 100}, "agent-b": {"karma": 70}})

        # Seed a market with one existing stake from agent-b (karma already deducted above)
        markets = _empty_markets()
        existing_stake = {
            "agent_id": "agent-b", "side": "yes", "amount": 30,
            "timestamp": "2026-01-10T00:00:00Z",
        }
        _make_market(markets, "market-1", "agent-a",
                     resolve_date="2026-02-01T00:00:00Z",
                     stakes=[existing_stake])
        (tmp_state / "markets.json").write_text(json.dumps(markets, indent=2))

        # agent-a resolves with "yes" after resolve_date
        write_delta(
            tmp_state / "inbox", "agent-a", "resolve_prediction",
            {"market_id": "market-1", "resolution": "yes"},
            timestamp="2026-02-02T00:00:00Z",
        )

        result = run_inbox(tmp_state)
        assert result.returncode == 0, f"process_inbox failed: {result.stderr}"

        markets_out = json.loads((tmp_state / "markets.json").read_text())
        assert markets_out["markets"]["market-1"]["status"] == "resolved"
        assert markets_out["markets"]["market-1"]["resolution"] == "yes"

        # agent-b was only winner: 30/30 = 100% of 30 pool = 30 karma back → 70 + 30 = 100
        agents_out = json.loads((tmp_state / "agents.json").read_text())
        assert agents_out["agents"]["agent-b"]["karma"] == 100
