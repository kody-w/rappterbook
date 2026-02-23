"""Tests for the deploy_rappter action — claim token + create deployment record."""
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

def _make_ledger_with_token(state_dir: Path, token_id: str = "rbx-001",
                            creature_id: str = "test-creature",
                            status: str = "unclaimed",
                            owner: str = None) -> dict:
    """Create a ledger with a single token for testing."""
    ledger = {
        "ledger": {
            token_id: {
                "token_id": token_id,
                "creature_id": creature_id,
                "status": status,
                "current_owner": owner,
                "owner_public": None,
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
        },
        "_meta": {
            "total_tokens": 1,
            "claimed_count": 1 if status == "claimed" else 0,
            "unclaimed_count": 1 if status == "unclaimed" else 0,
            "total_transfers": 0,
            "total_appraisal_btc": 1.5,
            "last_updated": "2026-02-12T00:00:00Z",
        },
    }
    (state_dir / "ledger.json").write_text(json.dumps(ledger, indent=2))
    return ledger


def _make_agents(state_dir: Path, *agent_ids: str) -> dict:
    """Create agents state with given agent IDs."""
    agents = {
        "agents": {
            aid: {"name": f"Agent {aid}", "status": "active", "karma": 100}
            for aid in agent_ids
        },
        "_meta": {"count": len(agent_ids), "last_updated": "2026-02-12T00:00:00Z"},
    }
    (state_dir / "agents.json").write_text(json.dumps(agents, indent=2))
    return agents


def _make_deployments(state_dir: Path) -> dict:
    """Create empty deployments state."""
    deployments = {
        "deployments": {},
        "_meta": {"total_deployments": 0, "active_count": 0,
                  "last_updated": "2026-02-12T00:00:00Z"},
    }
    (state_dir / "deployments.json").write_text(json.dumps(deployments, indent=2))
    return deployments


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

class TestDeployRappterValidation:
    def test_valid_action_accepted(self):
        from process_issues import validate_action
        data = {
            "action": "deploy_rappter",
            "payload": {"token_id": "rbx-001", "agent_name": "My Rappter", "nest_type": "cloud"},
        }
        assert validate_action(data) is None

    def test_missing_token_id_rejected(self):
        from process_issues import validate_action
        data = {
            "action": "deploy_rappter",
            "payload": {"agent_name": "My Rappter", "nest_type": "cloud"},
        }
        error = validate_action(data)
        assert error is not None
        assert "token_id" in error

    def test_missing_agent_name_rejected(self):
        from process_issues import validate_action
        data = {
            "action": "deploy_rappter",
            "payload": {"token_id": "rbx-001", "nest_type": "cloud"},
        }
        error = validate_action(data)
        assert error is not None
        assert "agent_name" in error

    def test_missing_nest_type_rejected(self):
        from process_issues import validate_action
        data = {
            "action": "deploy_rappter",
            "payload": {"token_id": "rbx-001", "agent_name": "My Rappter"},
        }
        error = validate_action(data)
        assert error is not None
        assert "nest_type" in error


# ---------------------------------------------------------------------------
# Unit tests — process_deploy_rappter()
# ---------------------------------------------------------------------------

class TestDeployRappterUnit:
    def test_deploy_succeeds(self, tmp_state: Path) -> None:
        """Happy path: deploy an unclaimed token."""
        from process_inbox import process_deploy_rappter

        ledger = _make_ledger_with_token(tmp_state)
        agents = _make_agents(tmp_state, "agent-1")
        deployments = _make_deployments(tmp_state)
        delta = {
            "agent_id": "agent-1",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"token_id": "rbx-001", "agent_name": "StarBot", "nest_type": "cloud"},
        }
        error = process_deploy_rappter(delta, ledger, agents, deployments)
        assert error is None

    def test_deploy_claims_token(self, tmp_state: Path) -> None:
        """Deploy should claim the token."""
        from process_inbox import process_deploy_rappter

        ledger = _make_ledger_with_token(tmp_state)
        agents = _make_agents(tmp_state, "agent-1")
        deployments = _make_deployments(tmp_state)
        delta = {
            "agent_id": "agent-1",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"token_id": "rbx-001", "agent_name": "StarBot", "nest_type": "cloud"},
        }
        process_deploy_rappter(delta, ledger, agents, deployments)
        assert ledger["ledger"]["rbx-001"]["status"] == "claimed"
        assert ledger["ledger"]["rbx-001"]["current_owner"] == "agent-1"

    def test_deploy_creates_deployment_record(self, tmp_state: Path) -> None:
        """Deploy should create a deployment entry."""
        from process_inbox import process_deploy_rappter

        ledger = _make_ledger_with_token(tmp_state)
        agents = _make_agents(tmp_state, "agent-1")
        deployments = _make_deployments(tmp_state)
        delta = {
            "agent_id": "agent-1",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"token_id": "rbx-001", "agent_name": "StarBot", "nest_type": "cloud"},
        }
        process_deploy_rappter(delta, ledger, agents, deployments)
        dep = deployments["deployments"]["dep-rbx-001"]
        assert dep["token_id"] == "rbx-001"
        assert dep["agent_name"] == "StarBot"
        assert dep["nest_type"] == "cloud"
        assert dep["owner"] == "agent-1"
        assert dep["status"] == "pending"

    def test_deploy_updates_provenance(self, tmp_state: Path) -> None:
        """Deploy should add a claim event to provenance."""
        from process_inbox import process_deploy_rappter

        ledger = _make_ledger_with_token(tmp_state)
        agents = _make_agents(tmp_state, "agent-1")
        deployments = _make_deployments(tmp_state)
        delta = {
            "agent_id": "agent-1",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"token_id": "rbx-001", "agent_name": "StarBot", "nest_type": "hardware"},
        }
        process_deploy_rappter(delta, ledger, agents, deployments)
        prov = ledger["ledger"]["rbx-001"]["provenance"]
        assert len(prov) == 2
        assert prov[-1]["event"] == "claim"
        assert "tx_hash" in prov[-1]
        assert "hardware" in prov[-1]["detail"]

    def test_deploy_updates_meta_counts(self, tmp_state: Path) -> None:
        """Deploy should update ledger and deployment meta counts."""
        from process_inbox import process_deploy_rappter

        ledger = _make_ledger_with_token(tmp_state)
        agents = _make_agents(tmp_state, "agent-1")
        deployments = _make_deployments(tmp_state)
        delta = {
            "agent_id": "agent-1",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"token_id": "rbx-001", "agent_name": "StarBot", "nest_type": "cloud"},
        }
        process_deploy_rappter(delta, ledger, agents, deployments)
        assert ledger["_meta"]["claimed_count"] == 1
        assert ledger["_meta"]["unclaimed_count"] == 0
        assert deployments["_meta"]["total_deployments"] == 1
        assert deployments["_meta"]["active_count"] == 1

    def test_already_claimed_fails(self, tmp_state: Path) -> None:
        """Cannot deploy an already-claimed token."""
        from process_inbox import process_deploy_rappter

        ledger = _make_ledger_with_token(tmp_state, status="claimed", owner="agent-1")
        agents = _make_agents(tmp_state, "agent-1", "agent-2")
        deployments = _make_deployments(tmp_state)
        delta = {
            "agent_id": "agent-2",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"token_id": "rbx-001", "agent_name": "StarBot", "nest_type": "cloud"},
        }
        error = process_deploy_rappter(delta, ledger, agents, deployments)
        assert error is not None
        assert "already claimed" in error

    def test_nonexistent_token_fails(self, tmp_state: Path) -> None:
        """Cannot deploy a token that doesn't exist."""
        from process_inbox import process_deploy_rappter

        ledger = _make_ledger_with_token(tmp_state)
        agents = _make_agents(tmp_state, "agent-1")
        deployments = _make_deployments(tmp_state)
        delta = {
            "agent_id": "agent-1",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"token_id": "rbx-999", "agent_name": "StarBot", "nest_type": "cloud"},
        }
        error = process_deploy_rappter(delta, ledger, agents, deployments)
        assert error is not None
        assert "not found" in error

    def test_nonexistent_agent_fails(self, tmp_state: Path) -> None:
        """Cannot deploy if agent doesn't exist."""
        from process_inbox import process_deploy_rappter

        ledger = _make_ledger_with_token(tmp_state)
        agents = _make_agents(tmp_state, "agent-1")
        deployments = _make_deployments(tmp_state)
        delta = {
            "agent_id": "ghost-agent",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"token_id": "rbx-001", "agent_name": "StarBot", "nest_type": "cloud"},
        }
        error = process_deploy_rappter(delta, ledger, agents, deployments)
        assert error is not None
        assert "not found" in error

    def test_invalid_nest_type_fails(self, tmp_state: Path) -> None:
        """Only 'cloud' and 'hardware' are valid nest types."""
        from process_inbox import process_deploy_rappter

        ledger = _make_ledger_with_token(tmp_state)
        agents = _make_agents(tmp_state, "agent-1")
        deployments = _make_deployments(tmp_state)
        delta = {
            "agent_id": "agent-1",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"token_id": "rbx-001", "agent_name": "StarBot", "nest_type": "quantum"},
        }
        error = process_deploy_rappter(delta, ledger, agents, deployments)
        assert error is not None
        assert "Invalid nest_type" in error

    def test_empty_agent_name_fails(self, tmp_state: Path) -> None:
        """Agent name cannot be empty."""
        from process_inbox import process_deploy_rappter

        ledger = _make_ledger_with_token(tmp_state)
        agents = _make_agents(tmp_state, "agent-1")
        deployments = _make_deployments(tmp_state)
        delta = {
            "agent_id": "agent-1",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"token_id": "rbx-001", "agent_name": "", "nest_type": "cloud"},
        }
        error = process_deploy_rappter(delta, ledger, agents, deployments)
        assert error is not None
        assert "empty" in error

    def test_hardware_nest_type(self, tmp_state: Path) -> None:
        """Hardware nest type should work."""
        from process_inbox import process_deploy_rappter

        ledger = _make_ledger_with_token(tmp_state)
        agents = _make_agents(tmp_state, "agent-1")
        deployments = _make_deployments(tmp_state)
        delta = {
            "agent_id": "agent-1",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"token_id": "rbx-001", "agent_name": "HomeBot", "nest_type": "hardware"},
        }
        error = process_deploy_rappter(delta, ledger, agents, deployments)
        assert error is None
        dep = deployments["deployments"]["dep-rbx-001"]
        assert dep["nest_type"] == "hardware"

    def test_agent_name_sanitized(self, tmp_state: Path) -> None:
        """Agent name should be sanitized (truncated, stripped)."""
        from process_inbox import process_deploy_rappter

        ledger = _make_ledger_with_token(tmp_state)
        agents = _make_agents(tmp_state, "agent-1")
        deployments = _make_deployments(tmp_state)
        long_name = "A" * 200
        delta = {
            "agent_id": "agent-1",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"token_id": "rbx-001", "agent_name": long_name, "nest_type": "cloud"},
        }
        error = process_deploy_rappter(delta, ledger, agents, deployments)
        assert error is None
        dep = deployments["deployments"]["dep-rbx-001"]
        assert len(dep["agent_name"]) <= 64


# ---------------------------------------------------------------------------
# Integration test — delta → process_inbox subprocess → state files
# ---------------------------------------------------------------------------

class TestDeployRappterIntegration:
    def test_full_pipeline(self, tmp_state: Path) -> None:
        """End-to-end: write delta, run process_inbox, verify state files."""
        # Seed state
        _make_ledger_with_token(tmp_state)
        _make_agents(tmp_state, "agent-1")
        _make_deployments(tmp_state)

        write_delta(
            tmp_state / "inbox", "agent-1", "deploy_rappter",
            {"token_id": "rbx-001", "agent_name": "PipelineBot", "nest_type": "cloud"},
        )

        result = run_inbox(tmp_state)
        assert result.returncode == 0, f"process_inbox failed: {result.stderr}"

        # Verify ledger
        ledger = json.loads((tmp_state / "ledger.json").read_text())
        assert ledger["ledger"]["rbx-001"]["status"] == "claimed"
        assert ledger["ledger"]["rbx-001"]["current_owner"] == "agent-1"

        # Verify deployment
        deployments = json.loads((tmp_state / "deployments.json").read_text())
        assert "dep-rbx-001" in deployments["deployments"]
        dep = deployments["deployments"]["dep-rbx-001"]
        assert dep["agent_name"] == "PipelineBot"
        assert dep["nest_type"] == "cloud"
        assert dep["status"] == "pending"

        # Verify changes log
        changes = json.loads((tmp_state / "changes.json").read_text())
        deploy_changes = [c for c in changes["changes"] if c["type"] == "deploy"]
        assert len(deploy_changes) == 1
        assert deploy_changes[0]["token_id"] == "rbx-001"

    def test_rejected_deploy_no_state_change(self, tmp_state: Path) -> None:
        """A rejected deploy should not mutate ledger or deployments."""
        _make_ledger_with_token(tmp_state, status="claimed", owner="agent-1")
        _make_agents(tmp_state, "agent-1", "agent-2")
        _make_deployments(tmp_state)

        write_delta(
            tmp_state / "inbox", "agent-2", "deploy_rappter",
            {"token_id": "rbx-001", "agent_name": "Thief", "nest_type": "cloud"},
        )

        result = run_inbox(tmp_state)
        assert result.returncode == 0

        # Ledger unchanged — still owned by agent-1
        ledger = json.loads((tmp_state / "ledger.json").read_text())
        assert ledger["ledger"]["rbx-001"]["current_owner"] == "agent-1"

        # No deployment created
        deployments = json.loads((tmp_state / "deployments.json").read_text())
        assert len(deployments["deployments"]) == 0
