"""Tests for the challenge_battle action — deterministic Rappter combat."""
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
                "id": "creature-a",
                "name": "Alpha",
                "archetype": "warrior",
                "element": "logic",
                "rarity": "uncommon",
                "stats": {
                    "wisdom": 70, "creativity": 80, "debate": 60,
                    "empathy": 50, "persistence": 60, "curiosity": 65,
                },
                "skills": [
                    {"name": "Strike", "level": 3, "description": "A powerful strike"},
                    {"name": "Shield", "level": 2, "description": "A protective shield"},
                ],
                "background": "Test creature A",
                "signature_move": "Ultimate Strike",
            },
            "creature-b": {
                "id": "creature-b",
                "name": "Beta",
                "archetype": "defender",
                "element": "chaos",
                "rarity": "rare",
                "stats": {
                    "wisdom": 60, "creativity": 70, "debate": 55,
                    "empathy": 65, "persistence": 75, "curiosity": 50,
                },
                "skills": [
                    {"name": "Blast", "level": 4, "description": "An energy blast"},
                    {"name": "Heal", "level": 1, "description": "Minor healing"},
                ],
                "background": "Test creature B",
                "signature_move": "Final Blast",
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
    ledger = {"ledger": {}, "_meta": {
        "total_tokens": 0, "claimed_count": 0, "unclaimed_count": 0,
        "total_transfers": 0, "total_appraisal_btc": 0,
        "last_updated": "2026-02-12T00:00:00Z",
    }}
    for agent_id, (token_id, creature_id) in agents_tokens.items():
        ledger["ledger"][token_id] = {
            "token_id": token_id,
            "creature_id": creature_id,
            "status": "claimed",
            "current_owner": agent_id,
            "owner_public": f"Agent {agent_id}",
            "appraisal_btc": 1.5,
            "transfer_count": 0,
            "interaction_count": 0,
            "provenance": [
                {"event": "genesis", "timestamp": "2026-02-12T00:00:00Z",
                 "tx_hash": "abc123", "detail": "Genesis"}
            ],
            "listed_for_sale": False,
            "sale_price_btc": None,
        }
    ledger["_meta"]["total_tokens"] = len(ledger["ledger"])
    ledger["_meta"]["claimed_count"] = len(ledger["ledger"])
    (state_dir / "ledger.json").write_text(json.dumps(ledger, indent=2))
    return ledger


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


def _make_battles(state_dir: Path, battles_list: list = None) -> dict:
    """Create battles.json state."""
    battles = {
        "battles": battles_list or [],
        "_meta": {"total_battles": len(battles_list or []),
                  "last_updated": "2026-02-12T00:00:00Z"},
    }
    (state_dir / "archive").mkdir(exist_ok=True)
    (state_dir / "archive" / "battles.json").write_text(json.dumps(battles, indent=2))
    return battles


def _make_merges(state_dir: Path) -> dict:
    """Create empty merges state."""
    merges = {
        "merges": [],
        "_meta": {"total_merges": 0, "last_updated": "2026-02-12T00:00:00Z"},
    }
    (state_dir / "archive").mkdir(exist_ok=True)
    (state_dir / "archive" / "merges.json").write_text(json.dumps(merges, indent=2))
    return merges


def _setup_battle(tmp_state: Path):
    """Common setup for battle tests. Returns (agents, battles, ledger, ghost_profiles, merges)."""
    data_dir = tmp_state.parent / "data"
    ghost_profiles = _make_ghost_profiles(data_dir)
    agents = _make_agents(tmp_state, "agent-a", "agent-b")
    ledger = _make_ledger_with_tokens(tmp_state, {
        "agent-a": ("rbx-001", "creature-a"),
        "agent-b": ("rbx-002", "creature-b"),
    })
    battles = _make_battles(tmp_state)
    merges = _make_merges(tmp_state)
    return agents, battles, ledger, ghost_profiles, merges


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

class TestChallengeBattleValidation:
    def test_valid_action_accepted(self):
        """challenge_battle with target_agent should pass validation."""
        from process_issues import validate_action
        data = {
            "action": "challenge_battle",
            "payload": {"target_agent": "agent-b"},
        }
        assert validate_action(data) is None

    def test_missing_target_rejected(self):
        """challenge_battle without target_agent should fail."""
        from process_issues import validate_action
        data = {
            "action": "challenge_battle",
            "payload": {},
        }
        error = validate_action(data)
        assert error is not None
        assert "target_agent" in error


# ---------------------------------------------------------------------------
# Unit tests — process_challenge_battle()
# ---------------------------------------------------------------------------

class TestChallengeBattleUnit:
    def test_battle_succeeds(self, tmp_state: Path) -> None:
        """Happy path: two agents battle, returns None."""
        from process_inbox import process_challenge_battle
        agents, battles, ledger, ghost_profiles, merges = _setup_battle(tmp_state)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"target_agent": "agent-b"},
        }
        error = process_challenge_battle(delta, agents, battles, ledger, ghost_profiles, merges)
        assert error is None

    def test_battle_produces_winner(self, tmp_state: Path) -> None:
        """Battle should record a winner in battles.json."""
        from process_inbox import process_challenge_battle
        agents, battles, ledger, ghost_profiles, merges = _setup_battle(tmp_state)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"target_agent": "agent-b"},
        }
        process_challenge_battle(delta, agents, battles, ledger, ghost_profiles, merges)
        assert len(battles["battles"]) == 1
        record = battles["battles"][0]
        assert record["winner"] in ("agent-a", "agent-b")
        assert record["loser"] in ("agent-a", "agent-b")
        assert record["winner"] != record["loser"]

    def test_self_battle_rejected(self, tmp_state: Path) -> None:
        """Cannot battle yourself."""
        from process_inbox import process_challenge_battle
        agents, battles, ledger, ghost_profiles, merges = _setup_battle(tmp_state)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"target_agent": "agent-a"},
        }
        error = process_challenge_battle(delta, agents, battles, ledger, ghost_profiles, merges)
        assert error is not None
        assert "yourself" in error

    def test_dormant_agent_rejected(self, tmp_state: Path) -> None:
        """Cannot battle a dormant agent."""
        from process_inbox import process_challenge_battle
        data_dir = tmp_state.parent / "data"
        ghost_profiles = _make_ghost_profiles(data_dir)
        agents = _make_agents(tmp_state, "agent-a", "agent-b",
                              **{"agent-b": {"status": "dormant"}})
        ledger = _make_ledger_with_tokens(tmp_state, {
            "agent-a": ("rbx-001", "creature-a"),
            "agent-b": ("rbx-002", "creature-b"),
        })
        battles = _make_battles(tmp_state)
        merges = _make_merges(tmp_state)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"target_agent": "agent-b"},
        }
        error = process_challenge_battle(delta, agents, battles, ledger, ghost_profiles, merges)
        assert error is not None
        assert "not active" in error

    def test_unclaimed_token_rejected(self, tmp_state: Path) -> None:
        """Cannot battle without a claimed token."""
        from process_inbox import process_challenge_battle
        data_dir = tmp_state.parent / "data"
        ghost_profiles = _make_ghost_profiles(data_dir)
        agents = _make_agents(tmp_state, "agent-a", "agent-b")
        # No tokens claimed
        ledger = {"ledger": {}, "_meta": {
            "total_tokens": 0, "claimed_count": 0, "unclaimed_count": 0,
            "total_transfers": 0, "total_appraisal_btc": 0,
            "last_updated": "2026-02-12T00:00:00Z",
        }}
        battles = _make_battles(tmp_state)
        merges = _make_merges(tmp_state)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"target_agent": "agent-b"},
        }
        error = process_challenge_battle(delta, agents, battles, ledger, ghost_profiles, merges)
        assert error is not None
        assert "no claimed token" in error

    def test_cooldown_enforced(self, tmp_state: Path) -> None:
        """Second battle within 24h should be rejected."""
        from process_inbox import process_challenge_battle
        agents, battles, ledger, ghost_profiles, merges = _setup_battle(tmp_state)

        # First battle
        delta1 = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"target_agent": "agent-b"},
        }
        error1 = process_challenge_battle(delta1, agents, battles, ledger, ghost_profiles, merges)
        assert error1 is None

        # Second battle within 24h
        delta2 = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T18:00:00Z",
            "payload": {"target_agent": "agent-b"},
        }
        error2 = process_challenge_battle(delta2, agents, battles, ledger, ghost_profiles, merges)
        assert error2 is not None
        assert "cooldown" in error2

    def test_battle_updates_agent_stats(self, tmp_state: Path) -> None:
        """Winner gets battle_wins++, loser gets battle_losses++."""
        from process_inbox import process_challenge_battle
        agents, battles, ledger, ghost_profiles, merges = _setup_battle(tmp_state)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"target_agent": "agent-b"},
        }
        process_challenge_battle(delta, agents, battles, ledger, ghost_profiles, merges)
        record = battles["battles"][0]
        winner = record["winner"]
        loser = record["loser"]
        assert agents["agents"][winner].get("battle_wins", 0) == 1
        assert agents["agents"][loser].get("battle_losses", 0) == 1

    def test_battle_updates_appraisal(self, tmp_state: Path) -> None:
        """Winner's token should get +0.05 BTC appraisal."""
        from process_inbox import process_challenge_battle
        agents, battles, ledger, ghost_profiles, merges = _setup_battle(tmp_state)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"target_agent": "agent-b"},
        }
        process_challenge_battle(delta, agents, battles, ledger, ghost_profiles, merges)
        record = battles["battles"][0]
        winner = record["winner"]
        winner_token_id = "rbx-001" if winner == "agent-a" else "rbx-002"
        assert ledger["ledger"][winner_token_id]["appraisal_btc"] == pytest.approx(1.55, abs=0.01)

    def test_battle_deterministic(self, tmp_state: Path) -> None:
        """Same inputs should produce identical output."""
        from process_inbox import _compute_battle, _battle_hash_seed
        data_dir = tmp_state.parent / "data"
        gp = _make_ghost_profiles(data_dir)
        profile_a = gp["profiles"]["creature-a"]
        profile_b = gp["profiles"]["creature-b"]
        seed = _battle_hash_seed("agent-a", "agent-b", "2026-02-22T12:00:00Z")

        result1 = _compute_battle(profile_a, profile_b, seed)
        result2 = _compute_battle(profile_a, profile_b, seed)
        assert result1 == result2

    def test_element_advantage_applied(self, tmp_state: Path) -> None:
        """logic vs chaos should give logic 15% bonus damage."""
        from process_inbox import _compute_battle, _battle_hash_seed
        # Create two identical profiles, one with logic (advantage vs chaos), one with chaos
        base_stats = {"wisdom": 50, "creativity": 50, "debate": 50,
                      "empathy": 50, "persistence": 50, "curiosity": 50}
        profile_logic = {
            "name": "Logic", "element": "logic", "stats": base_stats,
            "skills": [{"name": "A", "level": 1, "description": "x"}],
            "signature_move": "sig",
        }
        profile_chaos = {
            "name": "Chaos", "element": "chaos", "stats": base_stats,
            "skills": [{"name": "A", "level": 1, "description": "x"}],
            "signature_move": "sig",
        }
        # Neutral: same element
        profile_neutral = {
            "name": "Neutral", "element": "wonder", "stats": base_stats,
            "skills": [{"name": "A", "level": 1, "description": "x"}],
            "signature_move": "sig",
        }
        seed = _battle_hash_seed("a", "b", "2026-02-22T12:00:00Z")
        result_advantage = _compute_battle(profile_logic, profile_chaos, seed)
        result_neutral = _compute_battle(profile_neutral, profile_chaos, seed)
        # With advantage, challenger should do better (lower defender HP %)
        assert result_advantage["defender_hp_pct"] <= result_neutral["defender_hp_pct"]

    def test_max_turns_enforced(self, tmp_state: Path) -> None:
        """Battle should not exceed 20 turns."""
        from process_inbox import _compute_battle, _battle_hash_seed
        # Very high persistence = high HP, hard to KO
        tank_stats = {"wisdom": 50, "creativity": 10, "debate": 50,
                      "empathy": 50, "persistence": 100, "curiosity": 50}
        profile = {
            "name": "Tank", "element": "wonder", "stats": tank_stats,
            "skills": [{"name": "A", "level": 1, "description": "x"}],
            "signature_move": "",
        }
        seed = _battle_hash_seed("a", "b", "2026-02-22T12:00:00Z")
        result = _compute_battle(profile, profile, seed)
        assert result["turns"] <= 20

    def test_play_by_play_generated(self, tmp_state: Path) -> None:
        """Battle should produce a non-empty play-by-play."""
        from process_inbox import process_challenge_battle
        agents, battles, ledger, ghost_profiles, merges = _setup_battle(tmp_state)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"target_agent": "agent-b"},
        }
        process_challenge_battle(delta, agents, battles, ledger, ghost_profiles, merges)
        record = battles["battles"][0]
        assert len(record["play_by_play"]) > 0
        assert all(isinstance(line, str) for line in record["play_by_play"])

    def test_signature_move_triggers(self, tmp_state: Path) -> None:
        """Signature move should trigger when HP drops below 25%."""
        from process_inbox import _compute_battle, _battle_hash_seed
        # High attack to quickly drop HP
        aggro_stats = {"wisdom": 50, "creativity": 90, "debate": 50,
                       "empathy": 10, "persistence": 30, "curiosity": 50}
        profile_a = {
            "name": "Aggro", "element": "wonder", "stats": aggro_stats,
            "skills": [{"name": "Big Hit", "level": 5, "description": "x"}],
            "signature_move": "Final Blow",
        }
        weak_stats = {"wisdom": 10, "creativity": 10, "debate": 10,
                      "empathy": 10, "persistence": 30, "curiosity": 10}
        profile_b = {
            "name": "Weak", "element": "wonder", "stats": weak_stats,
            "skills": [{"name": "Tap", "level": 1, "description": "x"}],
            "signature_move": "Desperate Strike",
        }
        seed = _battle_hash_seed("a", "b", "2026-02-22T12:00:00Z")
        result = _compute_battle(profile_a, profile_b, seed)
        # Check that at least one signature move triggered
        sig_lines = [l for l in result["play_by_play"] if "signature move" in l]
        assert len(sig_lines) >= 1

    def test_skill_triggers_at_correct_turn(self, tmp_state: Path) -> None:
        """Skill with level N should trigger at turn N*2."""
        from process_inbox import _compute_battle, _battle_hash_seed
        stats = {"wisdom": 50, "creativity": 50, "debate": 50,
                 "empathy": 50, "persistence": 80, "curiosity": 50}
        profile_a = {
            "name": "Skilled", "element": "wonder", "stats": stats,
            "skills": [{"name": "Level3Skill", "level": 3, "description": "x"}],
            "signature_move": "",
        }
        profile_b = {
            "name": "Other", "element": "wonder", "stats": stats,
            "skills": [{"name": "Level1Skill", "level": 1, "description": "x"}],
            "signature_move": "",
        }
        seed = _battle_hash_seed("a", "b", "2026-02-22T12:00:00Z")
        result = _compute_battle(profile_a, profile_b, seed)
        # Level 3 skill should trigger at turn 6
        skill_lines = [l for l in result["play_by_play"] if "Level3Skill" in l]
        if skill_lines:
            assert "Turn 6" in skill_lines[0]
        # Level 1 skill should trigger at turn 2
        skill_lines_b = [l for l in result["play_by_play"] if "Level1Skill" in l]
        if skill_lines_b:
            assert "Turn 2" in skill_lines_b[0]


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

class TestChallengeBattleIntegration:
    def test_full_pipeline(self, tmp_state: Path) -> None:
        """End-to-end: write delta, run process_inbox, verify state."""
        data_dir = tmp_state.parent / "data"
        _make_ghost_profiles(data_dir)
        _make_agents(tmp_state, "agent-a", "agent-b")
        _make_ledger_with_tokens(tmp_state, {
            "agent-a": ("rbx-001", "creature-a"),
            "agent-b": ("rbx-002", "creature-b"),
        })
        _make_battles(tmp_state)
        _make_merges(tmp_state)

        write_delta(
            tmp_state / "inbox", "agent-a", "challenge_battle",
            {"target_agent": "agent-b"},
        )

        result = run_inbox(tmp_state, data_dir)
        assert result.returncode == 0, f"process_inbox failed: {result.stderr}"

        # Verify battles state
        battles = json.loads((tmp_state / "archive" / "battles.json").read_text())
        assert len(battles["battles"]) == 1
        assert battles["battles"][0]["challenger"] == "agent-a"
        assert battles["battles"][0]["defender"] == "agent-b"

        # Verify changes log
        changes = json.loads((tmp_state / "changes.json").read_text())
        battle_changes = [c for c in changes["changes"] if c["type"] == "battle"]
        assert len(battle_changes) == 1

    def test_rejected_battle_no_state_change(self, tmp_state: Path) -> None:
        """A rejected battle should not mutate state."""
        data_dir = tmp_state.parent / "data"
        _make_ghost_profiles(data_dir)
        _make_agents(tmp_state, "agent-a")  # Only one agent — target missing
        _make_ledger_with_tokens(tmp_state, {
            "agent-a": ("rbx-001", "creature-a"),
        })
        _make_battles(tmp_state)
        _make_merges(tmp_state)

        write_delta(
            tmp_state / "inbox", "agent-a", "challenge_battle",
            {"target_agent": "agent-b"},
        )

        result = run_inbox(tmp_state, data_dir)
        assert result.returncode == 0

        # No battles recorded
        battles = json.loads((tmp_state / "archive" / "battles.json").read_text())
        assert len(battles["battles"]) == 0
