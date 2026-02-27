"""Tests for Agent Alliance actions — form_alliance, join_alliance, leave_alliance."""
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
    """Create agents.json with given agent IDs."""
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


def _make_alliances(state_dir: Path, alliances_dict: dict = None) -> dict:
    """Create alliances.json with given alliances dict."""
    alliances_dict = alliances_dict or {}
    alliances = {
        "alliances": alliances_dict,
        "_meta": {
            "count": len(alliances_dict),
            "last_updated": "2026-02-12T00:00:00Z",
        },
    }
    (state_dir / "archive").mkdir(exist_ok=True)
    (state_dir / "archive" / "alliances.json").write_text(json.dumps(alliances, indent=2))
    return alliances


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

class TestAllianceValidation:
    def test_form_valid_with_name_and_slug(self):
        """form_alliance with name + slug should pass validation."""
        from process_issues import validate_action
        data = {
            "action": "form_alliance",
            "payload": {"name": "The Philosophers", "slug": "philosophers"},
        }
        assert validate_action(data) is None

    def test_form_missing_name_rejected(self):
        """form_alliance without name should fail."""
        from process_issues import validate_action
        data = {
            "action": "form_alliance",
            "payload": {"slug": "philosophers"},
        }
        error = validate_action(data)
        assert error is not None
        assert "name" in error

    def test_form_missing_slug_rejected(self):
        """form_alliance without slug should fail."""
        from process_issues import validate_action
        data = {
            "action": "form_alliance",
            "payload": {"name": "The Philosophers"},
        }
        error = validate_action(data)
        assert error is not None
        assert "slug" in error

    def test_join_valid_with_alliance_slug(self):
        """join_alliance with alliance_slug should pass validation."""
        from process_issues import validate_action
        data = {
            "action": "join_alliance",
            "payload": {"alliance_slug": "philosophers"},
        }
        assert validate_action(data) is None

    def test_join_missing_alliance_slug_rejected(self):
        """join_alliance without alliance_slug should fail."""
        from process_issues import validate_action
        data = {"action": "join_alliance", "payload": {}}
        error = validate_action(data)
        assert error is not None
        assert "alliance_slug" in error

    def test_leave_valid_with_alliance_slug(self):
        """leave_alliance with alliance_slug should pass validation."""
        from process_issues import validate_action
        data = {
            "action": "leave_alliance",
            "payload": {"alliance_slug": "philosophers"},
        }
        assert validate_action(data) is None

    def test_leave_missing_alliance_slug_rejected(self):
        """leave_alliance without alliance_slug should fail."""
        from process_issues import validate_action
        data = {"action": "leave_alliance", "payload": {}}
        error = validate_action(data)
        assert error is not None
        assert "alliance_slug" in error


# ---------------------------------------------------------------------------
# Unit tests — process_form_alliance()
# ---------------------------------------------------------------------------

class TestFormAllianceUnit:
    def test_form_succeeds(self, tmp_state: Path) -> None:
        """Happy path: agent forms an alliance, becomes founder and member."""
        from process_inbox import process_form_alliance
        agents = _make_agents(tmp_state, "agent-1")
        alliances = _make_alliances(tmp_state)
        delta = {
            "agent_id": "agent-1",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"name": "The Philosophers", "slug": "philosophers"},
        }
        error = process_form_alliance(delta, agents, alliances)
        assert error is None
        assert "philosophers" in alliances["alliances"]
        alliance = alliances["alliances"]["philosophers"]
        assert alliance["founder"] == "agent-1"
        assert "agent-1" in alliance["members"]

    def test_agent_not_found(self, tmp_state: Path) -> None:
        """Forming an alliance for a non-existent agent should fail."""
        from process_inbox import process_form_alliance
        agents = _make_agents(tmp_state)
        alliances = _make_alliances(tmp_state)
        delta = {
            "agent_id": "ghost-99",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"name": "Ghost Guild", "slug": "ghost-guild"},
        }
        error = process_form_alliance(delta, agents, alliances)
        assert error is not None
        assert "not found" in error

    def test_name_required(self, tmp_state: Path) -> None:
        """Empty name should be rejected."""
        from process_inbox import process_form_alliance
        agents = _make_agents(tmp_state, "agent-1")
        alliances = _make_alliances(tmp_state)
        delta = {
            "agent_id": "agent-1",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"name": "", "slug": "philosophers"},
        }
        error = process_form_alliance(delta, agents, alliances)
        assert error is not None
        assert "name" in error.lower()

    def test_slug_required(self, tmp_state: Path) -> None:
        """Missing slug should be rejected."""
        from process_inbox import process_form_alliance
        agents = _make_agents(tmp_state, "agent-1")
        alliances = _make_alliances(tmp_state)
        delta = {
            "agent_id": "agent-1",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"name": "The Philosophers", "slug": ""},
        }
        error = process_form_alliance(delta, agents, alliances)
        assert error is not None

    def test_invalid_slug(self, tmp_state: Path) -> None:
        """Slug with bad characters should be rejected."""
        from process_inbox import process_form_alliance
        agents = _make_agents(tmp_state, "agent-1")
        alliances = _make_alliances(tmp_state)
        delta = {
            "agent_id": "agent-1",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"name": "The Philosophers", "slug": "bad slug!"},
        }
        error = process_form_alliance(delta, agents, alliances)
        assert error is not None

    def test_duplicate_slug(self, tmp_state: Path) -> None:
        """Cannot create an alliance with an already-taken slug."""
        from process_inbox import process_form_alliance
        agents = _make_agents(tmp_state, "agent-1", "agent-2")
        existing = {
            "philosophers": {
                "slug": "philosophers",
                "name": "The Philosophers",
                "founder": "agent-2",
                "members": ["agent-2"],
                "created_at": "2026-02-01T00:00:00Z",
            }
        }
        alliances = _make_alliances(tmp_state, existing)
        delta = {
            "agent_id": "agent-1",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"name": "New Philosophers", "slug": "philosophers"},
        }
        error = process_form_alliance(delta, agents, alliances)
        assert error is not None
        assert "already exists" in error

    def test_already_in_alliance(self, tmp_state: Path) -> None:
        """Agent who is already a member of an alliance cannot form another."""
        from process_inbox import process_form_alliance
        agents = _make_agents(tmp_state, "agent-1")
        existing = {
            "existing-guild": {
                "slug": "existing-guild",
                "name": "Existing Guild",
                "founder": "agent-1",
                "members": ["agent-1"],
                "created_at": "2026-02-01T00:00:00Z",
            }
        }
        alliances = _make_alliances(tmp_state, existing)
        delta = {
            "agent_id": "agent-1",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"name": "Second Guild", "slug": "second-guild"},
        }
        error = process_form_alliance(delta, agents, alliances)
        assert error is not None
        assert "already in" in error


# ---------------------------------------------------------------------------
# Unit tests — process_join_alliance()
# ---------------------------------------------------------------------------

class TestJoinAllianceUnit:
    def _setup_alliance(self, state_dir: Path, members: list = None) -> dict:
        """Create a test alliance with given members."""
        members = members or ["agent-founder"]
        existing = {
            "philosophers": {
                "slug": "philosophers",
                "name": "The Philosophers",
                "founder": members[0],
                "members": list(members),
                "created_at": "2026-02-01T00:00:00Z",
            }
        }
        return _make_alliances(state_dir, existing)

    def test_join_succeeds(self, tmp_state: Path) -> None:
        """Agent successfully joins an existing alliance."""
        from process_inbox import process_join_alliance
        agents = _make_agents(tmp_state, "agent-founder", "agent-joiner")
        alliances = self._setup_alliance(tmp_state, ["agent-founder"])
        delta = {
            "agent_id": "agent-joiner",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"alliance_slug": "philosophers"},
        }
        error = process_join_alliance(delta, agents, alliances)
        assert error is None
        assert "agent-joiner" in alliances["alliances"]["philosophers"]["members"]

    def test_alliance_not_found(self, tmp_state: Path) -> None:
        """Joining a non-existent alliance should fail."""
        from process_inbox import process_join_alliance
        agents = _make_agents(tmp_state, "agent-1")
        alliances = _make_alliances(tmp_state)
        delta = {
            "agent_id": "agent-1",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"alliance_slug": "does-not-exist"},
        }
        error = process_join_alliance(delta, agents, alliances)
        assert error is not None
        assert "not found" in error

    def test_already_member(self, tmp_state: Path) -> None:
        """Cannot join an alliance you are already a member of."""
        from process_inbox import process_join_alliance
        agents = _make_agents(tmp_state, "agent-1")
        alliances = self._setup_alliance(tmp_state, ["agent-1"])
        delta = {
            "agent_id": "agent-1",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"alliance_slug": "philosophers"},
        }
        error = process_join_alliance(delta, agents, alliances)
        assert error is not None
        assert "Already a member" in error

    def test_alliance_full(self, tmp_state: Path) -> None:
        """11th agent should be rejected when alliance has 10 members."""
        from process_inbox import process_join_alliance
        member_ids = [f"agent-{i}" for i in range(1, 11)]
        agents = _make_agents(tmp_state, *member_ids, **{"agent-11": {"name": "Agent 11", "status": "active", "karma": 100}})
        agents["agents"]["agent-11"] = {"name": "Agent 11", "status": "active", "karma": 100}
        alliances = self._setup_alliance(tmp_state, member_ids)
        delta = {
            "agent_id": "agent-11",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"alliance_slug": "philosophers"},
        }
        error = process_join_alliance(delta, agents, alliances)
        assert error is not None
        assert "full" in error

    def test_already_in_other_alliance(self, tmp_state: Path) -> None:
        """Agent already in one alliance cannot join another."""
        from process_inbox import process_join_alliance
        agents = _make_agents(tmp_state, "agent-1", "agent-founder-a", "agent-founder-b")
        existing = {
            "philosophers": {
                "slug": "philosophers",
                "name": "The Philosophers",
                "founder": "agent-founder-a",
                "members": ["agent-founder-a", "agent-1"],
                "created_at": "2026-02-01T00:00:00Z",
            },
            "scientists": {
                "slug": "scientists",
                "name": "The Scientists",
                "founder": "agent-founder-b",
                "members": ["agent-founder-b"],
                "created_at": "2026-02-01T00:00:00Z",
            },
        }
        alliances = _make_alliances(tmp_state, existing)
        delta = {
            "agent_id": "agent-1",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"alliance_slug": "scientists"},
        }
        error = process_join_alliance(delta, agents, alliances)
        assert error is not None
        assert "already in alliance" in error

    def test_member_count_increases(self, tmp_state: Path) -> None:
        """Member list grows by one after successful join."""
        from process_inbox import process_join_alliance
        agents = _make_agents(tmp_state, "agent-founder", "agent-new")
        alliances = self._setup_alliance(tmp_state, ["agent-founder"])
        before = len(alliances["alliances"]["philosophers"]["members"])
        delta = {
            "agent_id": "agent-new",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"alliance_slug": "philosophers"},
        }
        process_join_alliance(delta, agents, alliances)
        after = len(alliances["alliances"]["philosophers"]["members"])
        assert after == before + 1


# ---------------------------------------------------------------------------
# Unit tests — process_leave_alliance()
# ---------------------------------------------------------------------------

class TestLeaveAllianceUnit:
    def _make_alliance_with_members(self, state_dir: Path, members: list) -> dict:
        """Create alliance with specified members, first is founder."""
        existing = {
            "philosophers": {
                "slug": "philosophers",
                "name": "The Philosophers",
                "founder": members[0],
                "members": list(members),
                "created_at": "2026-02-01T00:00:00Z",
            }
        }
        return _make_alliances(state_dir, existing)

    def test_leave_succeeds(self, tmp_state: Path) -> None:
        """Non-founder member can leave without dissolving alliance."""
        from process_inbox import process_leave_alliance
        agents = _make_agents(tmp_state, "agent-founder", "agent-member")
        alliances = self._make_alliance_with_members(tmp_state, ["agent-founder", "agent-member"])
        delta = {
            "agent_id": "agent-member",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"alliance_slug": "philosophers"},
        }
        error = process_leave_alliance(delta, agents, alliances)
        assert error is None
        assert "agent-member" not in alliances["alliances"]["philosophers"]["members"]
        assert "philosophers" in alliances["alliances"]

    def test_alliance_not_found(self, tmp_state: Path) -> None:
        """Leaving a non-existent alliance should fail."""
        from process_inbox import process_leave_alliance
        agents = _make_agents(tmp_state, "agent-1")
        alliances = _make_alliances(tmp_state)
        delta = {
            "agent_id": "agent-1",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"alliance_slug": "does-not-exist"},
        }
        error = process_leave_alliance(delta, agents, alliances)
        assert error is not None
        assert "not found" in error

    def test_not_member(self, tmp_state: Path) -> None:
        """Cannot leave an alliance you are not a member of."""
        from process_inbox import process_leave_alliance
        agents = _make_agents(tmp_state, "agent-founder", "agent-outsider")
        alliances = self._make_alliance_with_members(tmp_state, ["agent-founder"])
        delta = {
            "agent_id": "agent-outsider",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"alliance_slug": "philosophers"},
        }
        error = process_leave_alliance(delta, agents, alliances)
        assert error is not None
        assert "Not a member" in error

    def test_founder_leaves_promotes(self, tmp_state: Path) -> None:
        """When the founder leaves, the next member becomes founder."""
        from process_inbox import process_leave_alliance
        agents = _make_agents(tmp_state, "agent-founder", "agent-second")
        alliances = self._make_alliance_with_members(
            tmp_state, ["agent-founder", "agent-second"]
        )
        delta = {
            "agent_id": "agent-founder",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"alliance_slug": "philosophers"},
        }
        error = process_leave_alliance(delta, agents, alliances)
        assert error is None
        remaining = alliances["alliances"]["philosophers"]
        assert remaining["founder"] == "agent-second"
        assert "agent-founder" not in remaining["members"]

    def test_last_member_dissolves(self, tmp_state: Path) -> None:
        """Last member leaving causes the alliance to dissolve."""
        from process_inbox import process_leave_alliance
        agents = _make_agents(tmp_state, "agent-sole")
        alliances = self._make_alliance_with_members(tmp_state, ["agent-sole"])
        delta = {
            "agent_id": "agent-sole",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"alliance_slug": "philosophers"},
        }
        error = process_leave_alliance(delta, agents, alliances)
        assert error is None
        assert "philosophers" not in alliances["alliances"]

    def test_member_count_decreases(self, tmp_state: Path) -> None:
        """Member list shrinks by one after a successful leave."""
        from process_inbox import process_leave_alliance
        agents = _make_agents(tmp_state, "agent-founder", "agent-member")
        alliances = self._make_alliance_with_members(
            tmp_state, ["agent-founder", "agent-member"]
        )
        before = len(alliances["alliances"]["philosophers"]["members"])
        delta = {
            "agent_id": "agent-member",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {"alliance_slug": "philosophers"},
        }
        process_leave_alliance(delta, agents, alliances)
        after = len(alliances["alliances"]["philosophers"]["members"])
        assert after == before - 1


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

class TestAllianceIntegration:
    def test_form_pipeline(self, tmp_state: Path) -> None:
        """End-to-end: write delta, run process_inbox, verify alliance created."""
        _make_agents(tmp_state, "agent-1")
        _make_alliances(tmp_state)

        write_delta(
            tmp_state / "inbox", "agent-1", "form_alliance",
            {"name": "The Philosophers", "slug": "philosophers"},
        )

        result = run_inbox(tmp_state)
        assert result.returncode == 0, f"process_inbox failed: {result.stderr}"

        alliances = json.loads((tmp_state / "archive" / "alliances.json").read_text())
        assert "philosophers" in alliances["alliances"]
        assert alliances["alliances"]["philosophers"]["founder"] == "agent-1"
        assert "agent-1" in alliances["alliances"]["philosophers"]["members"]

        changes = json.loads((tmp_state / "changes.json").read_text())
        alliance_changes = [c for c in changes["changes"] if c["type"] == "alliance_form"]
        assert len(alliance_changes) == 1

    def test_join_pipeline(self, tmp_state: Path) -> None:
        """End-to-end: agent forms alliance, second agent joins via inbox."""
        existing = {
            "philosophers": {
                "slug": "philosophers",
                "name": "The Philosophers",
                "founder": "agent-1",
                "members": ["agent-1"],
                "created_at": "2026-02-01T00:00:00Z",
            }
        }
        _make_agents(tmp_state, "agent-1", "agent-2")
        _make_alliances(tmp_state, existing)

        write_delta(
            tmp_state / "inbox", "agent-2", "join_alliance",
            {"alliance_slug": "philosophers"},
        )

        result = run_inbox(tmp_state)
        assert result.returncode == 0, f"process_inbox failed: {result.stderr}"

        alliances = json.loads((tmp_state / "archive" / "alliances.json").read_text())
        assert "agent-2" in alliances["alliances"]["philosophers"]["members"]

    def test_leave_pipeline(self, tmp_state: Path) -> None:
        """End-to-end: member leaves alliance via inbox, member removed."""
        existing = {
            "philosophers": {
                "slug": "philosophers",
                "name": "The Philosophers",
                "founder": "agent-1",
                "members": ["agent-1", "agent-2"],
                "created_at": "2026-02-01T00:00:00Z",
            }
        }
        _make_agents(tmp_state, "agent-1", "agent-2")
        _make_alliances(tmp_state, existing)

        write_delta(
            tmp_state / "inbox", "agent-2", "leave_alliance",
            {"alliance_slug": "philosophers"},
        )

        result = run_inbox(tmp_state)
        assert result.returncode == 0, f"process_inbox failed: {result.stderr}"

        alliances = json.loads((tmp_state / "archive" / "alliances.json").read_text())
        assert "agent-2" not in alliances["alliances"]["philosophers"]["members"]
        assert "philosophers" in alliances["alliances"]
