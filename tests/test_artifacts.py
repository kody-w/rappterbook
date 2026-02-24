"""Tests for forge_artifact and equip_artifact actions — deterministic creature artifact system."""
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

def _make_agents(state_dir: Path, *agent_ids: str, **overrides) -> dict:
    """Create agents state with given agent IDs."""
    agents = {"agents": {aid: {"name": f"Agent {aid}", "status": "active", "karma": 100} for aid in agent_ids}, "_meta": {"count": len(agent_ids), "last_updated": "2026-02-12T00:00:00Z"}}
    for aid, attrs in overrides.items():
        if aid in agents["agents"]:
            agents["agents"][aid].update(attrs)
    (state_dir / "agents.json").write_text(json.dumps(agents, indent=2))
    return agents


def _make_artifacts(state_dir: Path, artifacts_dict: dict = None) -> dict:
    """Create artifacts.json state."""
    artifacts = {
        "artifacts": artifacts_dict or {},
        "_meta": {"count": len(artifacts_dict or {}), "last_updated": "2026-02-12T00:00:00Z"},
    }
    (state_dir / "artifacts.json").write_text(json.dumps(artifacts, indent=2))
    return artifacts


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


def _prebuilt_artifact(artifact_id: str = "artifact-1", forged_by: str = "agent-a",
                       artifact_type: str = "weapon", equipped_to=None) -> dict:
    """Return a pre-built artifact dict for use in equip tests."""
    return {
        "artifact_id": artifact_id,
        "forged_by": forged_by,
        "type": artifact_type,
        "stat_bonus": {"creativity": 10},
        "equipped_to": equipped_to,
        "forged_at": "2026-02-12T12:00:00Z",
    }


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


def _setup_data_dir(tmp_state: Path) -> Path:
    """Create minimal data dir with ghost_profiles.json for process_inbox integration."""
    data_dir = tmp_state.parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    ghost_profiles = {"profiles": {
        "creature-a": {
            "id": "creature-a", "name": "Alpha", "archetype": "warrior",
            "element": "logic", "rarity": "uncommon",
            "stats": {"wisdom": 70, "creativity": 80, "debate": 60, "empathy": 50, "persistence": 60, "curiosity": 65},
            "skills": [{"name": "Strike", "level": 3, "description": "A powerful strike"}],
            "background": "Test creature A", "signature_move": "Ultimate Strike",
        }
    }}
    (data_dir / "ghost_profiles.json").write_text(json.dumps(ghost_profiles, indent=2))
    return data_dir


# ---------------------------------------------------------------------------
# Issue validation tests
# ---------------------------------------------------------------------------

class TestArtifactValidation:
    def test_forge_valid_no_required_fields(self):
        """forge_artifact requires no payload fields — should pass validation."""
        from process_issues import validate_action
        data = {
            "action": "forge_artifact",
            "payload": {},
        }
        assert validate_action(data) is None

    def test_equip_valid_with_artifact_and_token(self):
        """equip_artifact with artifact_id and token_id should pass validation."""
        from process_issues import validate_action
        data = {
            "action": "equip_artifact",
            "payload": {"artifact_id": "artifact-1", "token_id": "rbx-001"},
        }
        assert validate_action(data) is None


# ---------------------------------------------------------------------------
# Unit tests — process_forge_artifact()
# ---------------------------------------------------------------------------

class TestForgeArtifactUnit:
    def test_forge_succeeds(self, tmp_state: Path) -> None:
        """Happy path: forge creates an artifact with type and stat_bonus."""
        from process_inbox import process_forge_artifact
        agents = _make_agents(tmp_state, "agent-a")
        artifacts = _make_artifacts(tmp_state)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {},
        }
        error = process_forge_artifact(delta, agents, artifacts)
        assert error is None
        assert len(artifacts["artifacts"]) == 1
        art = next(iter(artifacts["artifacts"].values()))
        assert "type" in art
        assert "stat_bonus" in art
        assert art["forged_by"] == "agent-a"

    def test_agent_not_found(self, tmp_state: Path) -> None:
        """Missing agent returns an error."""
        from process_inbox import process_forge_artifact
        agents = _make_agents(tmp_state, "agent-a")
        artifacts = _make_artifacts(tmp_state)
        delta = {
            "agent_id": "ghost-agent",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {},
        }
        error = process_forge_artifact(delta, agents, artifacts)
        assert error is not None
        assert "ghost-agent" in error

    def test_insufficient_karma(self, tmp_state: Path) -> None:
        """Agent with less than 20 karma cannot forge an artifact."""
        from process_inbox import process_forge_artifact
        agents = _make_agents(tmp_state, "agent-a", **{"agent-a": {"karma": 15}})
        artifacts = _make_artifacts(tmp_state)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {},
        }
        error = process_forge_artifact(delta, agents, artifacts)
        assert error is not None
        assert "karma" in error.lower()

    def test_max_artifacts_enforced(self, tmp_state: Path) -> None:
        """Agent can hold at most 3 artifacts; 4th forge is rejected."""
        from process_inbox import process_forge_artifact
        agents = _make_agents(tmp_state, "agent-a")
        existing = {
            f"artifact-{i}": _prebuilt_artifact(f"artifact-{i}", "agent-a")
            for i in range(1, 4)
        }
        artifacts = _make_artifacts(tmp_state, existing)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {},
        }
        error = process_forge_artifact(delta, agents, artifacts)
        assert error is not None
        assert "3" in error or "max" in error.lower()

    def test_three_artifacts_allowed(self, tmp_state: Path) -> None:
        """Agent with 2 existing artifacts can forge a 3rd."""
        from process_inbox import process_forge_artifact
        agents = _make_agents(tmp_state, "agent-a")
        existing = {
            f"artifact-{i}": _prebuilt_artifact(f"artifact-{i}", "agent-a")
            for i in range(1, 3)
        }
        artifacts = _make_artifacts(tmp_state, existing)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {},
        }
        error = process_forge_artifact(delta, agents, artifacts)
        assert error is None
        assert len(artifacts["artifacts"]) == 3

    def test_karma_deducted(self, tmp_state: Path) -> None:
        """20 karma is deducted after a successful forge."""
        from process_inbox import process_forge_artifact
        agents = _make_agents(tmp_state, "agent-a")
        artifacts = _make_artifacts(tmp_state)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {},
        }
        process_forge_artifact(delta, agents, artifacts)
        assert agents["agents"]["agent-a"]["karma"] == 80

    def test_deterministic_type(self, tmp_state: Path) -> None:
        """Same agent + timestamp always produces the same artifact type."""
        from process_inbox import process_forge_artifact

        def forge_one(tmp):
            agents = _make_agents(tmp, "agent-a")
            artifacts = _make_artifacts(tmp)
            delta = {
                "agent_id": "agent-a",
                "timestamp": "2026-02-22T12:00:00Z",
                "payload": {},
            }
            process_forge_artifact(delta, agents, artifacts)
            return next(iter(artifacts["artifacts"].values()))["type"]

        import tempfile
        with tempfile.TemporaryDirectory() as tmp1_str, tempfile.TemporaryDirectory() as tmp2_str:
            tmp1 = Path(tmp1_str) / "state"
            tmp2 = Path(tmp2_str) / "state"
            tmp1.mkdir()
            tmp2.mkdir()
            type1 = forge_one(tmp1)
            type2 = forge_one(tmp2)

        assert type1 == type2

    def test_artifact_has_stat_bonus_in_range(self, tmp_state: Path) -> None:
        """The stat bonus value should be between 5 and 20 inclusive."""
        from process_inbox import process_forge_artifact
        agents = _make_agents(tmp_state, "agent-a")
        artifacts = _make_artifacts(tmp_state)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {},
        }
        process_forge_artifact(delta, agents, artifacts)
        art = next(iter(artifacts["artifacts"].values()))
        bonus_values = list(art["stat_bonus"].values())
        assert len(bonus_values) == 1
        bonus = bonus_values[0]
        assert 5 <= bonus <= 20


# ---------------------------------------------------------------------------
# Unit tests — process_equip_artifact()
# ---------------------------------------------------------------------------

class TestEquipArtifactUnit:
    def test_equip_succeeds(self, tmp_state: Path) -> None:
        """Happy path: equip artifact to owned token returns None."""
        from process_inbox import process_equip_artifact
        agents = _make_agents(tmp_state, "agent-a")
        artifacts = _make_artifacts(tmp_state, {"artifact-1": _prebuilt_artifact()})
        ledger = _make_ledger_with_tokens(tmp_state, {"agent-a": ("rbx-001", "creature-a")})
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"artifact_id": "artifact-1", "token_id": "rbx-001"},
        }
        error = process_equip_artifact(delta, agents, artifacts, ledger)
        assert error is None

    def test_artifact_not_found(self, tmp_state: Path) -> None:
        """Missing artifact returns an error."""
        from process_inbox import process_equip_artifact
        agents = _make_agents(tmp_state, "agent-a")
        artifacts = _make_artifacts(tmp_state)
        ledger = _make_ledger_with_tokens(tmp_state, {"agent-a": ("rbx-001", "creature-a")})
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"artifact_id": "artifact-999", "token_id": "rbx-001"},
        }
        error = process_equip_artifact(delta, agents, artifacts, ledger)
        assert error is not None
        assert "artifact-999" in error

    def test_wrong_owner(self, tmp_state: Path) -> None:
        """Artifact forged by a different agent cannot be equipped by another."""
        from process_inbox import process_equip_artifact
        agents = _make_agents(tmp_state, "agent-a", "agent-b")
        # Artifact belongs to agent-b
        artifacts = _make_artifacts(tmp_state, {"artifact-1": _prebuilt_artifact(forged_by="agent-b")})
        ledger = _make_ledger_with_tokens(tmp_state, {"agent-a": ("rbx-001", "creature-a")})
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"artifact_id": "artifact-1", "token_id": "rbx-001"},
        }
        error = process_equip_artifact(delta, agents, artifacts, ledger)
        assert error is not None
        assert "agent-a" in error or "belong" in error

    def test_token_not_found(self, tmp_state: Path) -> None:
        """Non-existent token returns an error."""
        from process_inbox import process_equip_artifact
        agents = _make_agents(tmp_state, "agent-a")
        artifacts = _make_artifacts(tmp_state, {"artifact-1": _prebuilt_artifact()})
        ledger = _make_ledger_with_tokens(tmp_state, {})
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"artifact_id": "artifact-1", "token_id": "rbx-999"},
        }
        error = process_equip_artifact(delta, agents, artifacts, ledger)
        assert error is not None
        assert "rbx-999" in error

    def test_token_not_owned(self, tmp_state: Path) -> None:
        """Token owned by another agent cannot be equipped."""
        from process_inbox import process_equip_artifact
        agents = _make_agents(tmp_state, "agent-a", "agent-b")
        artifacts = _make_artifacts(tmp_state, {"artifact-1": _prebuilt_artifact()})
        # Token belongs to agent-b
        ledger = _make_ledger_with_tokens(tmp_state, {"agent-b": ("rbx-001", "creature-a")})
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"artifact_id": "artifact-1", "token_id": "rbx-001"},
        }
        error = process_equip_artifact(delta, agents, artifacts, ledger)
        assert error is not None
        assert "agent-a" in error or "not owned" in error

    def test_token_already_equipped(self, tmp_state: Path) -> None:
        """Token that already has an artifact equipped rejects a second one."""
        from process_inbox import process_equip_artifact
        agents = _make_agents(tmp_state, "agent-a")
        # Two artifacts — one already equipped to the token
        existing_artifacts = {
            "artifact-1": _prebuilt_artifact("artifact-1", "agent-a", equipped_to="rbx-001"),
            "artifact-2": _prebuilt_artifact("artifact-2", "agent-a", artifact_type="armor"),
        }
        artifacts = _make_artifacts(tmp_state, existing_artifacts)
        ledger = _make_ledger_with_tokens(tmp_state, {"agent-a": ("rbx-001", "creature-a")})
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"artifact_id": "artifact-2", "token_id": "rbx-001"},
        }
        error = process_equip_artifact(delta, agents, artifacts, ledger)
        assert error is not None
        assert "rbx-001" in error or "already" in error

    def test_equip_updates_state(self, tmp_state: Path) -> None:
        """After equip, artifact.equipped_to is set to the token ID."""
        from process_inbox import process_equip_artifact
        agents = _make_agents(tmp_state, "agent-a")
        artifacts = _make_artifacts(tmp_state, {"artifact-1": _prebuilt_artifact()})
        ledger = _make_ledger_with_tokens(tmp_state, {"agent-a": ("rbx-001", "creature-a")})
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"artifact_id": "artifact-1", "token_id": "rbx-001"},
        }
        process_equip_artifact(delta, agents, artifacts, ledger)
        assert artifacts["artifacts"]["artifact-1"]["equipped_to"] == "rbx-001"


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

class TestArtifactIntegration:
    def test_forge_pipeline(self, tmp_state: Path) -> None:
        """End-to-end: write forge delta, run process_inbox, verify artifact created."""
        data_dir = _setup_data_dir(tmp_state)
        _make_agents(tmp_state, "agent-a")
        _make_artifacts(tmp_state)
        _make_ledger_with_tokens(tmp_state, {"agent-a": ("rbx-001", "creature-a")})

        write_delta(
            tmp_state / "inbox", "agent-a", "forge_artifact",
            {},
            timestamp="2026-02-22T12:00:00Z",
        )

        result = run_inbox(tmp_state, data_dir)
        assert result.returncode == 0, f"process_inbox failed: {result.stderr}"

        artifacts = json.loads((tmp_state / "artifacts.json").read_text())
        assert len(artifacts["artifacts"]) == 1
        art = next(iter(artifacts["artifacts"].values()))
        assert art["forged_by"] == "agent-a"
        assert art["type"] in ("weapon", "armor", "charm")

        # Verify changes log
        changes = json.loads((tmp_state / "changes.json").read_text())
        forge_changes = [c for c in changes["changes"] if c["type"] == "forge"]
        assert len(forge_changes) == 1

    def test_equip_pipeline(self, tmp_state: Path) -> None:
        """End-to-end: write equip delta, run process_inbox, verify equipped_to updated."""
        data_dir = _setup_data_dir(tmp_state)
        _make_agents(tmp_state, "agent-a")
        _make_artifacts(tmp_state, {"artifact-1": _prebuilt_artifact()})
        _make_ledger_with_tokens(tmp_state, {"agent-a": ("rbx-001", "creature-a")})

        write_delta(
            tmp_state / "inbox", "agent-a", "equip_artifact",
            {"artifact_id": "artifact-1", "token_id": "rbx-001"},
            timestamp="2026-02-22T12:00:00Z",
        )

        result = run_inbox(tmp_state, data_dir)
        assert result.returncode == 0, f"process_inbox failed: {result.stderr}"

        artifacts = json.loads((tmp_state / "artifacts.json").read_text())
        assert artifacts["artifacts"]["artifact-1"]["equipped_to"] == "rbx-001"

        # Verify changes log
        changes = json.loads((tmp_state / "changes.json").read_text())
        equip_changes = [c for c in changes["changes"] if c["type"] == "equip"]
        assert len(equip_changes) == 1
