"""Tests for the fuse_creatures action — deterministic creature offspring generation."""
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ghost_profiles(data_dir: Path, profiles: dict = None) -> dict:
    """Create ghost_profiles.json with test creature profiles."""
    if profiles is None:
        profiles = {
            "creature-a": {
                "id": "creature-a", "name": "Alpha", "archetype": "warrior",
                "element": "logic", "rarity": "uncommon",
                "stats": {"wisdom": 70, "creativity": 80, "debate": 60, "empathy": 50, "persistence": 60, "curiosity": 65},
                "skills": [{"name": "Strike", "level": 3, "description": "A powerful strike"}, {"name": "Shield", "level": 2, "description": "A protective shield"}],
                "background": "Test creature A", "signature_move": "Ultimate Strike",
            },
            "creature-b": {
                "id": "creature-b", "name": "Beta", "archetype": "defender",
                "element": "chaos", "rarity": "rare",
                "stats": {"wisdom": 60, "creativity": 70, "debate": 55, "empathy": 65, "persistence": 75, "curiosity": 50},
                "skills": [{"name": "Blast", "level": 4, "description": "An energy blast"}, {"name": "Heal", "level": 1, "description": "Minor healing"}],
                "background": "Test creature B", "signature_move": "Final Blast",
            },
        }
    gp = {"profiles": profiles}
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "ghost_profiles.json").write_text(json.dumps(gp, indent=2))
    return gp


def _make_ledger_with_tokens(state_dir: Path, agents_tokens: dict) -> dict:
    """Create a ledger with tokens mapped to agents.

    agents_tokens: {agent_id: (token_id, creature_id)}
    """
    ledger = {"ledger": {}, "_meta": {"total_tokens": 0, "claimed_count": 0, "unclaimed_count": 0, "total_transfers": 0, "total_appraisal_btc": 0, "last_updated": "2026-02-12T00:00:00Z"}}
    for agent_id, (token_id, creature_id) in agents_tokens.items():
        ledger["ledger"][token_id] = {
            "token_id": token_id, "creature_id": creature_id, "status": "claimed",
            "current_owner": agent_id, "owner_public": f"Agent {agent_id}",
            "appraisal_btc": 1.5, "transfer_count": 0, "interaction_count": 0,
            "provenance": [{"event": "genesis", "timestamp": "2026-02-12T00:00:00Z", "tx_hash": "abc123", "detail": "Genesis"}],
            "listed_for_sale": False, "sale_price_btc": None,
        }
    ledger["_meta"]["total_tokens"] = len(ledger["ledger"])
    ledger["_meta"]["claimed_count"] = len(ledger["ledger"])
    (state_dir / "ledger.json").write_text(json.dumps(ledger, indent=2))
    return ledger


def _make_agents(state_dir: Path, *agent_ids: str, **overrides) -> dict:
    """Create agents state with given agent IDs."""
    agents = {"agents": {aid: {"name": f"Agent {aid}", "status": "active", "karma": 100} for aid in agent_ids}, "_meta": {"count": len(agent_ids), "last_updated": "2026-02-12T00:00:00Z"}}
    for aid, attrs in overrides.items():
        if aid in agents["agents"]:
            agents["agents"][aid].update(attrs)
    (state_dir / "agents.json").write_text(json.dumps(agents, indent=2))
    return agents


def _make_merges(state_dir: Path) -> dict:
    """Create empty merges state."""
    merges = {"merges": [], "_meta": {"total_merges": 0, "last_updated": "2026-02-12T00:00:00Z"}}
    (state_dir / "merges.json").write_text(json.dumps(merges, indent=2))
    return merges


def _make_bloodlines(state_dir: Path, bloodlines_list: list = None) -> dict:
    """Create bloodlines.json state."""
    bl = {"bloodlines": bloodlines_list or [], "_meta": {"count": len(bloodlines_list or []), "last_updated": "2026-02-12T00:00:00Z"}}
    (state_dir / "bloodlines.json").write_text(json.dumps(bl, indent=2))
    return bl


def _setup_fuse(tmp_state: Path):
    """Common setup for fusion tests. Returns (agents, bloodlines, ledger, ghost_profiles, merges)."""
    data_dir = tmp_state.parent / "data"
    ghost_profiles = _make_ghost_profiles(data_dir)
    agents = _make_agents(tmp_state, "agent-a", "agent-b")
    ledger = _make_ledger_with_tokens(tmp_state, {
        "agent-a": ("rbx-001", "creature-a"),
        "agent-b": ("rbx-002", "creature-b"),
    })
    bloodlines = _make_bloodlines(tmp_state)
    merges = _make_merges(tmp_state)
    return agents, bloodlines, ledger, ghost_profiles, merges


def run_inbox(state_dir: Path, data_dir: Path = None):
    """Run process_inbox.py with the given state directory."""
    env = os.environ.copy()
    env["STATE_DIR"] = str(state_dir)
    if data_dir:
        env["DATA_DIR"] = str(data_dir)
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True, text=True, env=env, cwd=str(ROOT)
    )


# ---------------------------------------------------------------------------
# Issue validation tests
# ---------------------------------------------------------------------------

class TestFuseValidation:
    def test_valid_action_accepted(self):
        """fuse_creatures with partner_agent should pass validation."""
        from process_issues import validate_action
        data = {
            "action": "fuse_creatures",
            "payload": {"partner_agent": "agent-b"},
        }
        assert validate_action(data) is None


# ---------------------------------------------------------------------------
# Unit tests — process_fuse_creatures()
# ---------------------------------------------------------------------------

class TestFuseCreaturesUnit:
    def test_fuse_succeeds(self, tmp_state: Path) -> None:
        """Happy path: two agents fuse, offspring created, returns None."""
        from process_inbox import process_fuse_creatures
        agents, bloodlines, ledger, ghost_profiles, merges = _setup_fuse(tmp_state)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"partner_agent": "agent-b"},
        }
        error = process_fuse_creatures(delta, agents, bloodlines, ledger, ghost_profiles, merges)
        assert error is None

    def test_agent_not_found(self, tmp_state: Path) -> None:
        """Missing initiating agent returns error."""
        from process_inbox import process_fuse_creatures
        agents, bloodlines, ledger, ghost_profiles, merges = _setup_fuse(tmp_state)
        delta = {
            "agent_id": "ghost-agent",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"partner_agent": "agent-b"},
        }
        error = process_fuse_creatures(delta, agents, bloodlines, ledger, ghost_profiles, merges)
        assert error is not None
        assert "ghost-agent" in error

    def test_partner_not_found(self, tmp_state: Path) -> None:
        """Missing partner agent returns error."""
        from process_inbox import process_fuse_creatures
        agents, bloodlines, ledger, ghost_profiles, merges = _setup_fuse(tmp_state)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"partner_agent": "nobody"},
        }
        error = process_fuse_creatures(delta, agents, bloodlines, ledger, ghost_profiles, merges)
        assert error is not None
        assert "nobody" in error

    def test_self_fuse_blocked(self, tmp_state: Path) -> None:
        """Agent cannot fuse with themselves."""
        from process_inbox import process_fuse_creatures
        agents, bloodlines, ledger, ghost_profiles, merges = _setup_fuse(tmp_state)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"partner_agent": "agent-a"},
        }
        error = process_fuse_creatures(delta, agents, bloodlines, ledger, ghost_profiles, merges)
        assert error is not None
        assert "yourself" in error

    def test_insufficient_karma_agent_a(self, tmp_state: Path) -> None:
        """Initiating agent with less than 10 karma is rejected."""
        from process_inbox import process_fuse_creatures
        data_dir = tmp_state.parent / "data"
        ghost_profiles = _make_ghost_profiles(data_dir)
        agents = _make_agents(tmp_state, "agent-a", "agent-b", **{"agent-a": {"karma": 5}})
        ledger = _make_ledger_with_tokens(tmp_state, {
            "agent-a": ("rbx-001", "creature-a"),
            "agent-b": ("rbx-002", "creature-b"),
        })
        bloodlines = _make_bloodlines(tmp_state)
        merges = _make_merges(tmp_state)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"partner_agent": "agent-b"},
        }
        error = process_fuse_creatures(delta, agents, bloodlines, ledger, ghost_profiles, merges)
        assert error is not None
        assert "karma" in error.lower()

    def test_insufficient_karma_agent_b(self, tmp_state: Path) -> None:
        """Partner agent with less than 10 karma is rejected."""
        from process_inbox import process_fuse_creatures
        data_dir = tmp_state.parent / "data"
        ghost_profiles = _make_ghost_profiles(data_dir)
        agents = _make_agents(tmp_state, "agent-a", "agent-b", **{"agent-b": {"karma": 9}})
        ledger = _make_ledger_with_tokens(tmp_state, {
            "agent-a": ("rbx-001", "creature-a"),
            "agent-b": ("rbx-002", "creature-b"),
        })
        bloodlines = _make_bloodlines(tmp_state)
        merges = _make_merges(tmp_state)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"partner_agent": "agent-b"},
        }
        error = process_fuse_creatures(delta, agents, bloodlines, ledger, ghost_profiles, merges)
        assert error is not None
        assert "karma" in error.lower()

    def test_no_token_agent_a(self, tmp_state: Path) -> None:
        """Initiating agent with no claimed token is rejected."""
        from process_inbox import process_fuse_creatures
        data_dir = tmp_state.parent / "data"
        ghost_profiles = _make_ghost_profiles(data_dir)
        agents = _make_agents(tmp_state, "agent-a", "agent-b")
        # Only agent-b has a token
        ledger = _make_ledger_with_tokens(tmp_state, {
            "agent-b": ("rbx-002", "creature-b"),
        })
        bloodlines = _make_bloodlines(tmp_state)
        merges = _make_merges(tmp_state)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"partner_agent": "agent-b"},
        }
        error = process_fuse_creatures(delta, agents, bloodlines, ledger, ghost_profiles, merges)
        assert error is not None
        assert "agent-a" in error

    def test_no_token_agent_b(self, tmp_state: Path) -> None:
        """Partner agent with no claimed token is rejected."""
        from process_inbox import process_fuse_creatures
        data_dir = tmp_state.parent / "data"
        ghost_profiles = _make_ghost_profiles(data_dir)
        agents = _make_agents(tmp_state, "agent-a", "agent-b")
        # Only agent-a has a token
        ledger = _make_ledger_with_tokens(tmp_state, {
            "agent-a": ("rbx-001", "creature-a"),
        })
        bloodlines = _make_bloodlines(tmp_state)
        merges = _make_merges(tmp_state)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"partner_agent": "agent-b"},
        }
        error = process_fuse_creatures(delta, agents, bloodlines, ledger, ghost_profiles, merges)
        assert error is not None
        assert "agent-b" in error

    def test_cooldown_enforced(self, tmp_state: Path) -> None:
        """Second fuse within 7 days should be rejected."""
        from process_inbox import process_fuse_creatures
        agents, bloodlines, ledger, ghost_profiles, merges = _setup_fuse(tmp_state)

        # First fuse succeeds
        delta1 = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"partner_agent": "agent-b"},
        }
        error1 = process_fuse_creatures(delta1, agents, bloodlines, ledger, ghost_profiles, merges)
        assert error1 is None

        # Second fuse within 7 days is blocked
        delta2 = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-25T12:00:00Z",
            "payload": {"partner_agent": "agent-b"},
        }
        error2 = process_fuse_creatures(delta2, agents, bloodlines, ledger, ghost_profiles, merges)
        assert error2 is not None
        assert "cooldown" in error2

    def test_karma_deducted(self, tmp_state: Path) -> None:
        """Both agents lose 10 karma after a successful fuse."""
        from process_inbox import process_fuse_creatures
        agents, bloodlines, ledger, ghost_profiles, merges = _setup_fuse(tmp_state)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"partner_agent": "agent-b"},
        }
        process_fuse_creatures(delta, agents, bloodlines, ledger, ghost_profiles, merges)
        assert agents["agents"]["agent-a"]["karma"] == 90
        assert agents["agents"]["agent-b"]["karma"] == 90

    def test_offspring_token_created(self, tmp_state: Path) -> None:
        """New rbx-B1 token is added to the ledger after fusion."""
        from process_inbox import process_fuse_creatures
        agents, bloodlines, ledger, ghost_profiles, merges = _setup_fuse(tmp_state)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"partner_agent": "agent-b"},
        }
        process_fuse_creatures(delta, agents, bloodlines, ledger, ghost_profiles, merges)
        assert "rbx-B1" in ledger["ledger"]
        offspring_token = ledger["ledger"]["rbx-B1"]
        assert offspring_token["status"] == "claimed"
        assert offspring_token["current_owner"] == "agent-a"

    def test_offspring_stats_mutated(self, tmp_state: Path) -> None:
        """Offspring stats differ from pure parent averages due to hash mutation."""
        from process_inbox import process_fuse_creatures
        agents, bloodlines, ledger, ghost_profiles, merges = _setup_fuse(tmp_state)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"partner_agent": "agent-b"},
        }
        process_fuse_creatures(delta, agents, bloodlines, ledger, ghost_profiles, merges)
        offspring_profile = bloodlines["bloodlines"][0]["offspring_profile"]
        offspring_stats = offspring_profile["stats"]

        # Pure averages of parent stats
        stats_a = ghost_profiles["profiles"]["creature-a"]["stats"]
        stats_b = ghost_profiles["profiles"]["creature-b"]["stats"]
        pure_averages = {k: (stats_a.get(k, 50) + stats_b.get(k, 50)) / 2 for k in stats_a}

        # At least one stat should differ from pure average due to mutation
        mutations = [abs(offspring_stats[k] - pure_averages[k]) for k in pure_averages if k in offspring_stats]
        assert any(m > 0 for m in mutations), "All stats equal pure average — mutation not applied"

    def test_offspring_element_from_stronger(self, tmp_state: Path) -> None:
        """Element comes from the parent with higher total stats."""
        from process_inbox import process_fuse_creatures
        agents, bloodlines, ledger, ghost_profiles, merges = _setup_fuse(tmp_state)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"partner_agent": "agent-b"},
        }
        process_fuse_creatures(delta, agents, bloodlines, ledger, ghost_profiles, merges)
        offspring_profile = bloodlines["bloodlines"][0]["offspring_profile"]

        stats_a = ghost_profiles["profiles"]["creature-a"]["stats"]
        stats_b = ghost_profiles["profiles"]["creature-b"]["stats"]
        total_a = sum(stats_a.values())
        total_b = sum(stats_b.values())

        expected_element = (
            ghost_profiles["profiles"]["creature-a"]["element"]
            if total_a >= total_b
            else ghost_profiles["profiles"]["creature-b"]["element"]
        )
        assert offspring_profile["element"] == expected_element

    def test_offspring_rarity_upgrade(self, tmp_state: Path) -> None:
        """Offspring rarity is one tier above the lower parent rarity, capped at legendary."""
        from process_inbox import process_fuse_creatures
        agents, bloodlines, ledger, ghost_profiles, merges = _setup_fuse(tmp_state)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"partner_agent": "agent-b"},
        }
        process_fuse_creatures(delta, agents, bloodlines, ledger, ghost_profiles, merges)
        offspring_profile = bloodlines["bloodlines"][0]["offspring_profile"]

        # creature-a is uncommon (1), creature-b is rare (2)
        # lower = uncommon (1), one above = rare (2)
        assert offspring_profile["rarity"] == "rare"

    def test_offspring_rarity_capped_at_legendary(self, tmp_state: Path) -> None:
        """When both parents are legendary, offspring stays legendary."""
        from process_inbox import process_fuse_creatures
        data_dir = tmp_state.parent / "data"
        profiles = {
            "creature-a": {
                "id": "creature-a", "name": "Alpha", "archetype": "warrior",
                "element": "logic", "rarity": "legendary",
                "stats": {"wisdom": 70, "creativity": 80, "debate": 60, "empathy": 50, "persistence": 60, "curiosity": 65},
                "skills": [{"name": "Strike", "level": 3, "description": "x"}],
                "background": "A", "signature_move": "Sig A",
            },
            "creature-b": {
                "id": "creature-b", "name": "Beta", "archetype": "defender",
                "element": "chaos", "rarity": "legendary",
                "stats": {"wisdom": 60, "creativity": 70, "debate": 55, "empathy": 65, "persistence": 75, "curiosity": 50},
                "skills": [{"name": "Blast", "level": 4, "description": "x"}],
                "background": "B", "signature_move": "Sig B",
            },
        }
        ghost_profiles = _make_ghost_profiles(data_dir, profiles)
        agents = _make_agents(tmp_state, "agent-a", "agent-b")
        ledger = _make_ledger_with_tokens(tmp_state, {
            "agent-a": ("rbx-001", "creature-a"),
            "agent-b": ("rbx-002", "creature-b"),
        })
        bloodlines = _make_bloodlines(tmp_state)
        merges = _make_merges(tmp_state)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"partner_agent": "agent-b"},
        }
        process_fuse_creatures(delta, agents, bloodlines, ledger, ghost_profiles, merges)
        offspring_profile = bloodlines["bloodlines"][0]["offspring_profile"]
        assert offspring_profile["rarity"] == "legendary"

    def test_deterministic(self, tmp_state: Path) -> None:
        """Same inputs produce identical offspring profiles."""
        from process_inbox import process_fuse_creatures

        def do_fuse(tmp):
            data_dir = tmp / "data"
            agents = _make_agents(tmp, "agent-a", "agent-b")
            ledger = _make_ledger_with_tokens(tmp, {
                "agent-a": ("rbx-001", "creature-a"),
                "agent-b": ("rbx-002", "creature-b"),
            })
            bloodlines = _make_bloodlines(tmp)
            merges = _make_merges(tmp)
            ghost_profiles = _make_ghost_profiles(data_dir)
            delta = {
                "agent_id": "agent-a",
                "timestamp": "2026-02-22T12:00:00Z",
                "payload": {"partner_agent": "agent-b"},
            }
            process_fuse_creatures(delta, agents, bloodlines, ledger, ghost_profiles, merges)
            return bloodlines["bloodlines"][0]["offspring_profile"]

        import tempfile
        with tempfile.TemporaryDirectory() as tmp1_str, tempfile.TemporaryDirectory() as tmp2_str:
            tmp1 = Path(tmp1_str) / "state"
            tmp2 = Path(tmp2_str) / "state"
            tmp1.mkdir()
            tmp2.mkdir()
            profile1 = do_fuse(tmp1)
            profile2 = do_fuse(tmp2)

        assert profile1["stats"] == profile2["stats"]
        assert profile1["element"] == profile2["element"]
        assert profile1["rarity"] == profile2["rarity"]

    def test_bloodline_record_created(self, tmp_state: Path) -> None:
        """A bloodline record is written after a successful fuse."""
        from process_inbox import process_fuse_creatures
        agents, bloodlines, ledger, ghost_profiles, merges = _setup_fuse(tmp_state)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"partner_agent": "agent-b"},
        }
        process_fuse_creatures(delta, agents, bloodlines, ledger, ghost_profiles, merges)
        assert len(bloodlines["bloodlines"]) == 1
        record = bloodlines["bloodlines"][0]
        assert record["parent_a"] == "agent-a"
        assert record["parent_b"] == "agent-b"
        assert record["offspring_token_id"] == "rbx-B1"
        assert "offspring_profile" in record


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

class TestFuseIntegration:
    def test_full_pipeline(self, tmp_state: Path) -> None:
        """End-to-end: write delta, run process_inbox, verify state."""
        data_dir = tmp_state.parent / "data"
        _make_ghost_profiles(data_dir)
        _make_agents(tmp_state, "agent-a", "agent-b")
        _make_ledger_with_tokens(tmp_state, {
            "agent-a": ("rbx-001", "creature-a"),
            "agent-b": ("rbx-002", "creature-b"),
        })
        _make_bloodlines(tmp_state)
        _make_merges(tmp_state)

        write_delta(
            tmp_state / "inbox", "agent-a", "fuse_creatures",
            {"partner_agent": "agent-b"},
            timestamp="2026-02-22T12:00:00Z",
        )

        result = run_inbox(tmp_state, data_dir)
        assert result.returncode == 0, f"process_inbox failed: {result.stderr}"

        # Verify bloodlines state
        bloodlines = json.loads((tmp_state / "bloodlines.json").read_text())
        assert len(bloodlines["bloodlines"]) == 1
        record = bloodlines["bloodlines"][0]
        assert record["parent_a"] == "agent-a"
        assert record["parent_b"] == "agent-b"

        # Verify offspring token in ledger
        ledger = json.loads((tmp_state / "ledger.json").read_text())
        assert "rbx-B1" in ledger["ledger"]

        # Verify changes log
        changes = json.loads((tmp_state / "changes.json").read_text())
        fuse_changes = [c for c in changes["changes"] if c["type"] == "fuse_creature"]
        assert len(fuse_changes) == 1

    def test_rejected_no_state_change(self, tmp_state: Path) -> None:
        """A rejected fuse (self-fuse) should not mutate state."""
        data_dir = tmp_state.parent / "data"
        _make_ghost_profiles(data_dir)
        _make_agents(tmp_state, "agent-a")
        _make_ledger_with_tokens(tmp_state, {
            "agent-a": ("rbx-001", "creature-a"),
        })
        _make_bloodlines(tmp_state)
        _make_merges(tmp_state)

        write_delta(
            tmp_state / "inbox", "agent-a", "fuse_creatures",
            {"partner_agent": "agent-a"},  # self-fuse, invalid
            timestamp="2026-02-22T12:00:00Z",
        )

        result = run_inbox(tmp_state, data_dir)
        assert result.returncode == 0

        # No bloodlines recorded
        bloodlines = json.loads((tmp_state / "bloodlines.json").read_text())
        assert len(bloodlines["bloodlines"]) == 0

        # No offspring token in ledger
        ledger = json.loads((tmp_state / "ledger.json").read_text())
        assert "rbx-B1" not in ledger["ledger"]
