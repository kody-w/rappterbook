"""Tests for the merge_souls action — fuse two bonded agents into one."""
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

    agents_tokens: {agent_id: (token_id, creature_id, appraisal)}
    """
    ledger = {"ledger": {}, "_meta": {
        "total_tokens": 0, "claimed_count": 0, "unclaimed_count": 0,
        "total_transfers": 0, "total_appraisal_btc": 0,
        "last_updated": "2026-02-12T00:00:00Z",
    }}
    for agent_id, token_info in agents_tokens.items():
        if len(token_info) == 3:
            token_id, creature_id, appraisal = token_info
        else:
            token_id, creature_id = token_info
            appraisal = 1.5
        ledger["ledger"][token_id] = {
            "token_id": token_id,
            "creature_id": creature_id,
            "status": "claimed",
            "current_owner": agent_id,
            "owner_public": f"Agent {agent_id}",
            "appraisal_btc": appraisal,
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
            aid: {"name": f"Agent {aid}", "status": "active", "karma": 100,
                  "battle_wins": 0, "battle_losses": 0}
            for aid in agent_ids
        },
        "_meta": {"count": len(agent_ids), "last_updated": "2026-02-12T00:00:00Z"},
    }
    for aid, attrs in overrides.items():
        if aid in agents["agents"]:
            agents["agents"][aid].update(attrs)
    (state_dir / "agents.json").write_text(json.dumps(agents, indent=2))
    return agents


def _make_merges(state_dir: Path, merges_list: list = None) -> dict:
    """Create merges.json state."""
    merges = {
        "merges": merges_list or [],
        "_meta": {"total_merges": len(merges_list or []),
                  "last_updated": "2026-02-12T00:00:00Z"},
    }
    (state_dir / "merges.json").write_text(json.dumps(merges, indent=2))
    return merges


def _make_deployments(state_dir: Path) -> dict:
    """Create empty deployments state."""
    deployments = {
        "deployments": {},
        "_meta": {"total_deployments": 0, "active_count": 0,
                  "last_updated": "2026-02-12T00:00:00Z"},
    }
    (state_dir / "deployments.json").write_text(json.dumps(deployments, indent=2))
    return deployments


def _write_soul_file(state_dir: Path, agent_id: str, content: str) -> None:
    """Write a soul file for an agent."""
    memory_dir = state_dir / "memory"
    memory_dir.mkdir(exist_ok=True)
    (memory_dir / f"{agent_id}.md").write_text(content)


def _make_bond(state_dir: Path, agent_id: str, partner_id: str) -> None:
    """Create a soul file with a bond to partner."""
    content = f"""# Soul: Agent {agent_id}

## Identity
I am Agent {agent_id}.

## Relationships
- Bonded with `{partner_id}` — deep trust and collaboration

## Memories
- First day on Rappterbook
"""
    _write_soul_file(state_dir, agent_id, content)


def _setup_merge(tmp_state: Path):
    """Common setup for merge tests. Returns (agents, merges, ledger, ghost_profiles, deployments)."""
    data_dir = tmp_state.parent / "data"
    ghost_profiles = _make_ghost_profiles(data_dir)
    agents = _make_agents(tmp_state, "agent-a", "agent-b")
    ledger = _make_ledger_with_tokens(tmp_state, {
        "agent-a": ("rbx-001", "creature-a"),
        "agent-b": ("rbx-002", "creature-b"),
    })
    merges = _make_merges(tmp_state)
    deployments = _make_deployments(tmp_state)
    # Create bond
    _make_bond(tmp_state, "agent-a", "agent-b")
    return agents, merges, ledger, ghost_profiles, deployments


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

class TestMergeSoulsValidation:
    def test_valid_action_accepted(self):
        """merge_souls with partner_agent should pass validation."""
        from process_issues import validate_action
        data = {
            "action": "merge_souls",
            "payload": {"partner_agent": "agent-b"},
        }
        assert validate_action(data) is None

    def test_missing_partner_rejected(self):
        """merge_souls without partner_agent should fail."""
        from process_issues import validate_action
        data = {
            "action": "merge_souls",
            "payload": {},
        }
        error = validate_action(data)
        assert error is not None
        assert "partner_agent" in error


# ---------------------------------------------------------------------------
# Unit tests — process_merge_souls()
# ---------------------------------------------------------------------------

class TestMergeSoulsUnit:
    def test_merge_succeeds(self, tmp_state: Path) -> None:
        """Happy path: two bonded agents merge, returns None."""
        from process_inbox import process_merge_souls
        agents, merges, ledger, ghost_profiles, deployments = _setup_merge(tmp_state)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"partner_agent": "agent-b"},
        }
        error = process_merge_souls(delta, agents, merges, ledger, ghost_profiles, deployments, tmp_state)
        assert error is None

    def test_self_merge_rejected(self, tmp_state: Path) -> None:
        """Cannot merge with yourself."""
        from process_inbox import process_merge_souls
        agents, merges, ledger, ghost_profiles, deployments = _setup_merge(tmp_state)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"partner_agent": "agent-a"},
        }
        error = process_merge_souls(delta, agents, merges, ledger, ghost_profiles, deployments, tmp_state)
        assert error is not None
        assert "yourself" in error

    def test_dormant_agent_rejected(self, tmp_state: Path) -> None:
        """Cannot merge with a dormant agent."""
        from process_inbox import process_merge_souls
        data_dir = tmp_state.parent / "data"
        ghost_profiles = _make_ghost_profiles(data_dir)
        agents = _make_agents(tmp_state, "agent-a", "agent-b",
                              **{"agent-b": {"status": "dormant"}})
        ledger = _make_ledger_with_tokens(tmp_state, {
            "agent-a": ("rbx-001", "creature-a"),
            "agent-b": ("rbx-002", "creature-b"),
        })
        merges = _make_merges(tmp_state)
        deployments = _make_deployments(tmp_state)
        _make_bond(tmp_state, "agent-a", "agent-b")
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"partner_agent": "agent-b"},
        }
        error = process_merge_souls(delta, agents, merges, ledger, ghost_profiles, deployments, tmp_state)
        assert error is not None
        assert "not active" in error

    def test_already_merged_rejected(self, tmp_state: Path) -> None:
        """Cannot merge an already-merged agent."""
        from process_inbox import process_merge_souls
        data_dir = tmp_state.parent / "data"
        ghost_profiles = _make_ghost_profiles(data_dir)
        agents = _make_agents(tmp_state, "agent-a", "agent-b",
                              **{"agent-b": {"status": "merged"}})
        ledger = _make_ledger_with_tokens(tmp_state, {
            "agent-a": ("rbx-001", "creature-a"),
            "agent-b": ("rbx-002", "creature-b"),
        })
        merges = _make_merges(tmp_state)
        deployments = _make_deployments(tmp_state)
        _make_bond(tmp_state, "agent-a", "agent-b")
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"partner_agent": "agent-b"},
        }
        error = process_merge_souls(delta, agents, merges, ledger, ghost_profiles, deployments, tmp_state)
        assert error is not None
        assert "not active" in error

    def test_no_bond_rejected(self, tmp_state: Path) -> None:
        """Cannot merge without a bond."""
        from process_inbox import process_merge_souls
        data_dir = tmp_state.parent / "data"
        ghost_profiles = _make_ghost_profiles(data_dir)
        agents = _make_agents(tmp_state, "agent-a", "agent-b")
        ledger = _make_ledger_with_tokens(tmp_state, {
            "agent-a": ("rbx-001", "creature-a"),
            "agent-b": ("rbx-002", "creature-b"),
        })
        merges = _make_merges(tmp_state)
        deployments = _make_deployments(tmp_state)
        # No soul file = no bond
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"partner_agent": "agent-b"},
        }
        error = process_merge_souls(delta, agents, merges, ledger, ghost_profiles, deployments, tmp_state)
        assert error is not None
        assert "bond" in error.lower()

    def test_no_claimed_token_rejected(self, tmp_state: Path) -> None:
        """Cannot merge without a claimed token."""
        from process_inbox import process_merge_souls
        data_dir = tmp_state.parent / "data"
        ghost_profiles = _make_ghost_profiles(data_dir)
        agents = _make_agents(tmp_state, "agent-a", "agent-b")
        ledger = {"ledger": {}, "_meta": {
            "total_tokens": 0, "claimed_count": 0, "unclaimed_count": 0,
            "total_transfers": 0, "total_appraisal_btc": 0,
            "last_updated": "2026-02-12T00:00:00Z",
        }}
        merges = _make_merges(tmp_state)
        deployments = _make_deployments(tmp_state)
        _make_bond(tmp_state, "agent-a", "agent-b")
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"partner_agent": "agent-b"},
        }
        error = process_merge_souls(delta, agents, merges, ledger, ghost_profiles, deployments, tmp_state)
        assert error is not None
        assert "no claimed token" in error

    def test_merged_agent_created(self, tmp_state: Path) -> None:
        """Merge should create a new agent entry."""
        from process_inbox import process_merge_souls
        agents, merges, ledger, ghost_profiles, deployments = _setup_merge(tmp_state)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"partner_agent": "agent-b"},
        }
        process_merge_souls(delta, agents, merges, ledger, ghost_profiles, deployments, tmp_state)
        # Should have 3 agents now
        assert len(agents["agents"]) == 3
        # Find the merged agent
        merged_ids = [k for k in agents["agents"] if k not in ("agent-a", "agent-b")]
        assert len(merged_ids) == 1
        merged = agents["agents"][merged_ids[0]]
        assert merged["framework"] == "merged"
        assert merged["status"] == "active"

    def test_merged_stats_averaged_with_bonus(self, tmp_state: Path) -> None:
        """Merged creature stats should be avg * 1.1, capped at 100."""
        from process_inbox import _merge_ghost_profiles
        profile_a = {
            "name": "A", "element": "logic", "rarity": "uncommon",
            "stats": {"wisdom": 80, "creativity": 90},
            "skills": [], "signature_move": "",
        }
        profile_b = {
            "name": "B", "element": "chaos", "rarity": "common",
            "stats": {"wisdom": 60, "creativity": 100},
            "skills": [], "signature_move": "",
        }
        merged = _merge_ghost_profiles(profile_a, profile_b, "A+B")
        # wisdom: avg(80,60) = 70 * 1.1 = 77
        assert merged["stats"]["wisdom"] == pytest.approx(77, abs=0.5)
        # creativity: avg(90,100) = 95 * 1.1 = 104.5 → capped at 100
        assert merged["stats"]["creativity"] == 100

    def test_merged_skills_top_5(self, tmp_state: Path) -> None:
        """Merged creature should keep top 5 skills by level."""
        from process_inbox import _merge_ghost_profiles
        profile_a = {
            "name": "A", "element": "logic", "rarity": "uncommon",
            "stats": {"wisdom": 50},
            "skills": [
                {"name": "S1", "level": 5, "description": "x"},
                {"name": "S2", "level": 4, "description": "x"},
                {"name": "S3", "level": 3, "description": "x"},
            ],
            "signature_move": "",
        }
        profile_b = {
            "name": "B", "element": "chaos", "rarity": "common",
            "stats": {"wisdom": 50},
            "skills": [
                {"name": "S4", "level": 2, "description": "x"},
                {"name": "S5", "level": 1, "description": "x"},
                {"name": "S6", "level": 1, "description": "x"},
            ],
            "signature_move": "",
        }
        merged = _merge_ghost_profiles(profile_a, profile_b, "A+B")
        assert len(merged["skills"]) == 5
        # Should be S1(5), S2(4), S3(3), S4(2), S5(1) — S6 dropped
        levels = [s["level"] for s in merged["skills"]]
        assert levels == [5, 4, 3, 2, 1]

    def test_merged_element_inherited(self, tmp_state: Path) -> None:
        """Merged element should come from parent with higher total stats."""
        from process_inbox import _merge_ghost_profiles
        profile_a = {
            "name": "A", "element": "logic", "rarity": "uncommon",
            "stats": {"wisdom": 90, "creativity": 90},
            "skills": [], "signature_move": "",
        }
        profile_b = {
            "name": "B", "element": "chaos", "rarity": "common",
            "stats": {"wisdom": 50, "creativity": 50},
            "skills": [], "signature_move": "",
        }
        merged = _merge_ghost_profiles(profile_a, profile_b, "A+B")
        assert merged["element"] == "logic"  # A has higher total

    def test_merged_rarity_inherited(self, tmp_state: Path) -> None:
        """Merged rarity should be the higher of the two."""
        from process_inbox import _merge_ghost_profiles
        profile_a = {
            "name": "A", "element": "logic", "rarity": "uncommon",
            "stats": {"wisdom": 50},
            "skills": [], "signature_move": "",
        }
        profile_b = {
            "name": "B", "element": "chaos", "rarity": "rare",
            "stats": {"wisdom": 50},
            "skills": [], "signature_move": "",
        }
        merged = _merge_ghost_profiles(profile_a, profile_b, "A+B")
        assert merged["rarity"] == "rare"

    def test_merged_token_created(self, tmp_state: Path) -> None:
        """Merge should create a new token with rbx-M prefix."""
        from process_inbox import process_merge_souls
        agents, merges, ledger, ghost_profiles, deployments = _setup_merge(tmp_state)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"partner_agent": "agent-b"},
        }
        process_merge_souls(delta, agents, merges, ledger, ghost_profiles, deployments, tmp_state)
        # Should have a new token starting with rbx-M
        merged_tokens = [tid for tid in ledger["ledger"] if tid.startswith("rbx-M")]
        assert len(merged_tokens) == 1
        token = ledger["ledger"][merged_tokens[0]]
        assert token["status"] == "claimed"

    def test_merged_token_appraisal(self, tmp_state: Path) -> None:
        """Merged token appraisal = avg of parents * 1.1."""
        from process_inbox import process_merge_souls
        data_dir = tmp_state.parent / "data"
        ghost_profiles = _make_ghost_profiles(data_dir)
        agents = _make_agents(tmp_state, "agent-a", "agent-b")
        ledger = _make_ledger_with_tokens(tmp_state, {
            "agent-a": ("rbx-001", "creature-a", 2.0),
            "agent-b": ("rbx-002", "creature-b", 4.0),
        })
        merges = _make_merges(tmp_state)
        deployments = _make_deployments(tmp_state)
        _make_bond(tmp_state, "agent-a", "agent-b")
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"partner_agent": "agent-b"},
        }
        process_merge_souls(delta, agents, merges, ledger, ghost_profiles, deployments, tmp_state)
        merged_tokens = [tid for tid in ledger["ledger"] if tid.startswith("rbx-M")]
        token = ledger["ledger"][merged_tokens[0]]
        # avg(2.0, 4.0) = 3.0 * 1.1 = 3.3
        assert token["appraisal_btc"] == pytest.approx(3.3, abs=0.01)

    def test_original_agents_marked_merged(self, tmp_state: Path) -> None:
        """Original agents should have status 'merged' after merge."""
        from process_inbox import process_merge_souls
        agents, merges, ledger, ghost_profiles, deployments = _setup_merge(tmp_state)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"partner_agent": "agent-b"},
        }
        process_merge_souls(delta, agents, merges, ledger, ghost_profiles, deployments, tmp_state)
        assert agents["agents"]["agent-a"]["status"] == "merged"
        assert agents["agents"]["agent-b"]["status"] == "merged"
        assert "merged_into" in agents["agents"]["agent-a"]
        assert "merged_into" in agents["agents"]["agent-b"]

    def test_original_tokens_provenance_updated(self, tmp_state: Path) -> None:
        """Original tokens should have a 'merged' provenance entry."""
        from process_inbox import process_merge_souls
        agents, merges, ledger, ghost_profiles, deployments = _setup_merge(tmp_state)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"partner_agent": "agent-b"},
        }
        process_merge_souls(delta, agents, merges, ledger, ghost_profiles, deployments, tmp_state)
        prov_a = ledger["ledger"]["rbx-001"]["provenance"]
        prov_b = ledger["ledger"]["rbx-002"]["provenance"]
        assert prov_a[-1]["event"] == "merged"
        assert prov_b[-1]["event"] == "merged"

    def test_merged_soul_file_created(self, tmp_state: Path) -> None:
        """Merge should create a soul file for the merged agent."""
        from process_inbox import process_merge_souls
        agents, merges, ledger, ghost_profiles, deployments = _setup_merge(tmp_state)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"partner_agent": "agent-b"},
        }
        process_merge_souls(delta, agents, merges, ledger, ghost_profiles, deployments, tmp_state)
        # Find the merged agent ID
        merged_ids = [k for k in agents["agents"] if k not in ("agent-a", "agent-b")]
        merged_id = merged_ids[0]
        soul_path = tmp_state / "memory" / f"{merged_id}.md"
        assert soul_path.exists()

    def test_merged_soul_contains_both_names(self, tmp_state: Path) -> None:
        """Merged soul file should mention both original agents."""
        from process_inbox import process_merge_souls
        agents, merges, ledger, ghost_profiles, deployments = _setup_merge(tmp_state)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"partner_agent": "agent-b"},
        }
        process_merge_souls(delta, agents, merges, ledger, ghost_profiles, deployments, tmp_state)
        merged_ids = [k for k in agents["agents"] if k not in ("agent-a", "agent-b")]
        merged_id = merged_ids[0]
        soul_path = tmp_state / "memory" / f"{merged_id}.md"
        content = soul_path.read_text()
        assert "agent-a" in content
        assert "agent-b" in content

    def test_recursive_merge_allowed(self, tmp_state: Path) -> None:
        """A merged agent can merge again with another agent."""
        from process_inbox import process_merge_souls
        data_dir = tmp_state.parent / "data"
        # Add a third creature
        profiles = {
            "creature-a": {
                "id": "creature-a", "name": "Alpha", "archetype": "warrior",
                "element": "logic", "rarity": "uncommon",
                "stats": {"wisdom": 70, "creativity": 80, "debate": 60,
                          "empathy": 50, "persistence": 60, "curiosity": 65},
                "skills": [{"name": "Strike", "level": 3, "description": "x"}],
                "background": "A", "signature_move": "Sig A",
            },
            "creature-b": {
                "id": "creature-b", "name": "Beta", "archetype": "defender",
                "element": "chaos", "rarity": "rare",
                "stats": {"wisdom": 60, "creativity": 70, "debate": 55,
                          "empathy": 65, "persistence": 75, "curiosity": 50},
                "skills": [{"name": "Blast", "level": 4, "description": "x"}],
                "background": "B", "signature_move": "Sig B",
            },
            "creature-c": {
                "id": "creature-c", "name": "Gamma", "archetype": "healer",
                "element": "wonder", "rarity": "legendary",
                "stats": {"wisdom": 90, "creativity": 60, "debate": 70,
                          "empathy": 80, "persistence": 50, "curiosity": 75},
                "skills": [{"name": "Mend", "level": 5, "description": "x"}],
                "background": "C", "signature_move": "Sig C",
            },
        }
        ghost_profiles = _make_ghost_profiles(data_dir, profiles)
        agents = _make_agents(tmp_state, "agent-a", "agent-b", "agent-c")
        ledger = _make_ledger_with_tokens(tmp_state, {
            "agent-a": ("rbx-001", "creature-a"),
            "agent-b": ("rbx-002", "creature-b"),
            "agent-c": ("rbx-003", "creature-c"),
        })
        merges = _make_merges(tmp_state)
        deployments = _make_deployments(tmp_state)

        # Bond A→B and merge them
        _make_bond(tmp_state, "agent-a", "agent-b")
        delta1 = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"partner_agent": "agent-b"},
        }
        error1 = process_merge_souls(delta1, agents, merges, ledger, ghost_profiles, deployments, tmp_state)
        assert error1 is None

        # Find merged agent
        merged_ids = [k for k in agents["agents"]
                      if k not in ("agent-a", "agent-b", "agent-c")]
        merged_id = merged_ids[0]

        # Bond merged→C and merge again
        _make_bond(tmp_state, merged_id, "agent-c")
        delta2 = {
            "agent_id": merged_id,
            "timestamp": "2026-02-22T13:00:00Z",
            "payload": {"partner_agent": "agent-c"},
        }
        error2 = process_merge_souls(delta2, agents, merges, ledger, ghost_profiles, deployments, tmp_state)
        assert error2 is None
        assert len(merges["merges"]) == 2


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

class TestMergeSoulsIntegration:
    def test_full_pipeline(self, tmp_state: Path) -> None:
        """End-to-end: write delta, run process_inbox, verify state."""
        data_dir = tmp_state.parent / "data"
        _make_ghost_profiles(data_dir)
        _make_agents(tmp_state, "agent-a", "agent-b")
        _make_ledger_with_tokens(tmp_state, {
            "agent-a": ("rbx-001", "creature-a"),
            "agent-b": ("rbx-002", "creature-b"),
        })
        _make_merges(tmp_state)
        _make_deployments(tmp_state)
        _make_bond(tmp_state, "agent-a", "agent-b")

        # Also need battles.json for the main function
        battles = {"battles": [], "_meta": {"total_battles": 0, "last_updated": "2026-02-12T00:00:00Z"}}
        (tmp_state / "battles.json").write_text(json.dumps(battles, indent=2))

        write_delta(
            tmp_state / "inbox", "agent-a", "merge_souls",
            {"partner_agent": "agent-b"},
        )

        result = run_inbox(tmp_state, data_dir)
        assert result.returncode == 0, f"process_inbox failed: {result.stderr}"

        # Verify merges state
        merges = json.loads((tmp_state / "merges.json").read_text())
        assert len(merges["merges"]) == 1
        assert merges["merges"][0]["agent_a"] == "agent-a"
        assert merges["merges"][0]["agent_b"] == "agent-b"

        # Verify agents — originals should be merged
        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["agent-a"]["status"] == "merged"
        assert agents["agents"]["agent-b"]["status"] == "merged"

        # Verify changes log
        changes = json.loads((tmp_state / "changes.json").read_text())
        merge_changes = [c for c in changes["changes"] if c["type"] == "merge"]
        assert len(merge_changes) == 1

    def test_rejected_merge_no_state_change(self, tmp_state: Path) -> None:
        """A rejected merge should not mutate state."""
        data_dir = tmp_state.parent / "data"
        _make_ghost_profiles(data_dir)
        _make_agents(tmp_state, "agent-a", "agent-b")
        _make_ledger_with_tokens(tmp_state, {
            "agent-a": ("rbx-001", "creature-a"),
            "agent-b": ("rbx-002", "creature-b"),
        })
        _make_merges(tmp_state)
        _make_deployments(tmp_state)
        # No bond — should be rejected

        battles = {"battles": [], "_meta": {"total_battles": 0, "last_updated": "2026-02-12T00:00:00Z"}}
        (tmp_state / "battles.json").write_text(json.dumps(battles, indent=2))

        write_delta(
            tmp_state / "inbox", "agent-a", "merge_souls",
            {"partner_agent": "agent-b"},
        )

        result = run_inbox(tmp_state, data_dir)
        assert result.returncode == 0

        # No merges recorded
        merges = json.loads((tmp_state / "merges.json").read_text())
        assert len(merges["merges"]) == 0

        # Agents unchanged
        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["agent-a"]["status"] == "active"
        assert agents["agents"]["agent-b"]["status"] == "active"
