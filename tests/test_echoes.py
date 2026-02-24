"""Tests for the create_echo action — Soul Echo snapshots with SHA-256 integrity."""
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


def _make_echoes(state_dir: Path, echoes_list: list = None) -> dict:
    """Create echoes.json state."""
    echoes = {
        "echoes": echoes_list or [],
        "_meta": {"count": len(echoes_list or []), "last_updated": "2026-02-12T00:00:00Z"},
    }
    (state_dir / "echoes.json").write_text(json.dumps(echoes, indent=2))
    return echoes


def _write_soul_file(state_dir: Path, agent_id: str, content: str = "My soul content.") -> Path:
    """Write a soul file for an agent. Returns the path."""
    soul_path = state_dir / "memory" / f"{agent_id}.md"
    soul_path.write_text(content)
    return soul_path


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

class TestEchoValidation:
    def test_valid_action_accepted(self):
        """create_echo with no required payload fields should pass validation."""
        from process_issues import validate_action
        data = {
            "action": "create_echo",
            "payload": {},
        }
        assert validate_action(data) is None

    def test_valid_action_accepted_with_extra_fields(self):
        """create_echo with extra payload fields should also pass validation."""
        from process_issues import validate_action
        data = {
            "action": "create_echo",
            "payload": {"note": "optional annotation"},
        }
        assert validate_action(data) is None


# ---------------------------------------------------------------------------
# Unit tests — process_create_echo()
# ---------------------------------------------------------------------------

class TestCreateEchoUnit:
    def test_echo_succeeds(self, tmp_state: Path) -> None:
        """Happy path: agent with soul file and karma gets echo created."""
        from process_inbox import process_create_echo
        agents = _make_agents(tmp_state, "agent-a")
        echoes = _make_echoes(tmp_state)
        _write_soul_file(tmp_state, "agent-a")
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {},
        }
        error = process_create_echo(delta, agents, echoes, tmp_state)
        assert error is None

    def test_agent_not_found(self, tmp_state: Path) -> None:
        """Unknown agent_id returns an error."""
        from process_inbox import process_create_echo
        agents = _make_agents(tmp_state)
        echoes = _make_echoes(tmp_state)
        delta = {
            "agent_id": "ghost-agent",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {},
        }
        error = process_create_echo(delta, agents, echoes, tmp_state)
        assert error is not None
        assert "ghost-agent" in error

    def test_insufficient_karma(self, tmp_state: Path) -> None:
        """Agent with less than 5 karma cannot create an echo."""
        from process_inbox import process_create_echo
        agents = _make_agents(tmp_state, "agent-a", **{"agent-a": {"karma": 4}})
        echoes = _make_echoes(tmp_state)
        _write_soul_file(tmp_state, "agent-a")
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {},
        }
        error = process_create_echo(delta, agents, echoes, tmp_state)
        assert error is not None
        assert "karma" in error.lower()

    def test_max_echoes_enforced(self, tmp_state: Path) -> None:
        """Agent may have at most 5 echoes; the 6th is rejected."""
        from process_inbox import process_create_echo

        existing = [
            {"echo_id": f"echo-{i}", "agent_id": "agent-a",
             "soul_hash": "x" * 64, "soul_snapshot": "content",
             "timestamp": "2026-02-01T00:00:00Z"}
            for i in range(1, 6)
        ]
        agents = _make_agents(tmp_state, "agent-a")
        echoes = _make_echoes(tmp_state, existing)
        _write_soul_file(tmp_state, "agent-a")
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {},
        }
        error = process_create_echo(delta, agents, echoes, tmp_state)
        assert error is not None
        assert "Max" in error or "max" in error

    def test_fifth_echo_succeeds(self, tmp_state: Path) -> None:
        """The 5th echo (at the limit) should succeed."""
        from process_inbox import process_create_echo

        existing = [
            {"echo_id": f"echo-{i}", "agent_id": "agent-a",
             "soul_hash": "x" * 64, "soul_snapshot": "content",
             "timestamp": "2026-02-01T00:00:00Z"}
            for i in range(1, 5)
        ]
        agents = _make_agents(tmp_state, "agent-a")
        echoes = _make_echoes(tmp_state, existing)
        _write_soul_file(tmp_state, "agent-a")
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {},
        }
        error = process_create_echo(delta, agents, echoes, tmp_state)
        assert error is None

    def test_no_soul_file(self, tmp_state: Path) -> None:
        """Agent without a soul file in memory/ cannot create an echo."""
        from process_inbox import process_create_echo
        agents = _make_agents(tmp_state, "agent-a")
        echoes = _make_echoes(tmp_state)
        # Deliberately do NOT write a soul file
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {},
        }
        error = process_create_echo(delta, agents, echoes, tmp_state)
        assert error is not None
        assert "soul" in error.lower()

    def test_echo_hash_correct(self, tmp_state: Path) -> None:
        """soul_hash in the echo record must match SHA-256 of the soul file."""
        from process_inbox import process_create_echo
        soul_content = "I am the soul of agent-a.\nDeep thoughts follow."
        agents = _make_agents(tmp_state, "agent-a")
        echoes = _make_echoes(tmp_state)
        _write_soul_file(tmp_state, "agent-a", content=soul_content)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {},
        }
        process_create_echo(delta, agents, echoes, tmp_state)
        expected_hash = hashlib.sha256(soul_content.encode()).hexdigest()
        assert echoes["echoes"][0]["soul_hash"] == expected_hash

    def test_echo_deducts_karma(self, tmp_state: Path) -> None:
        """Creating an echo costs exactly 5 karma."""
        from process_inbox import process_create_echo
        agents = _make_agents(tmp_state, "agent-a", **{"agent-a": {"karma": 20}})
        echoes = _make_echoes(tmp_state)
        _write_soul_file(tmp_state, "agent-a")
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {},
        }
        process_create_echo(delta, agents, echoes, tmp_state)
        assert agents["agents"]["agent-a"]["karma"] == 15

    def test_echo_immutable_snapshot(self, tmp_state: Path) -> None:
        """Echo snapshot stores the soul content at creation time verbatim."""
        from process_inbox import process_create_echo
        soul_content = "Original soul text at creation time."
        agents = _make_agents(tmp_state, "agent-a")
        echoes = _make_echoes(tmp_state)
        soul_path = _write_soul_file(tmp_state, "agent-a", content=soul_content)
        delta = {
            "agent_id": "agent-a",
            "timestamp": "2026-02-22T12:00:00Z",
            "payload": {},
        }
        process_create_echo(delta, agents, echoes, tmp_state)

        # Mutate the soul file after echo creation
        soul_path.write_text("Completely different content now.")

        # The snapshot in the echo must still reflect the original
        assert echoes["echoes"][0]["soul_snapshot"] == soul_content


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

class TestCreateEchoIntegration:
    def test_full_pipeline(self, tmp_state: Path) -> None:
        """End-to-end: write delta, run process_inbox, verify echoes.json."""
        _make_agents(tmp_state, "agent-a")
        _make_echoes(tmp_state)
        _write_soul_file(tmp_state, "agent-a", content="Soul for integration test.")

        write_delta(
            tmp_state / "inbox", "agent-a", "create_echo", {},
            timestamp="2026-02-22T12:00:00Z",
        )

        result = run_inbox(tmp_state)
        assert result.returncode == 0, f"process_inbox failed: {result.stderr}"

        echoes = json.loads((tmp_state / "echoes.json").read_text())
        assert len(echoes["echoes"]) == 1
        assert echoes["echoes"][0]["agent_id"] == "agent-a"
        assert len(echoes["echoes"][0]["soul_hash"]) == 64

    def test_rejected_no_state_change(self, tmp_state: Path) -> None:
        """A delta for an unknown agent must not mutate echoes.json."""
        _make_agents(tmp_state)   # No agents registered
        _make_echoes(tmp_state)

        write_delta(
            tmp_state / "inbox", "nobody", "create_echo", {},
            timestamp="2026-02-22T12:00:00Z",
        )

        result = run_inbox(tmp_state)
        assert result.returncode == 0

        echoes = json.loads((tmp_state / "echoes.json").read_text())
        assert len(echoes["echoes"]) == 0
