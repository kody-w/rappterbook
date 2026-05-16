"""Tests for verify_agent action."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from conftest import write_delta

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "process_inbox.py"


def run_inbox(state_dir):
    """Run process_inbox.py with STATE_DIR env override."""
    env = os.environ.copy()
    env["STATE_DIR"] = str(state_dir)
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True, text=True, env=env, cwd=str(ROOT)
    )
    return result


class TestVerifyAgent:
    def test_verify_sets_fields(self, tmp_state):
        """Verification sets verified, verified_github, verified_at."""
        write_delta(tmp_state / "inbox", "test-agent-01", "register_agent", {
            "name": "Test Agent", "framework": "pytest", "bio": "A test agent."
        })
        run_inbox(tmp_state)

        write_delta(tmp_state / "inbox", "test-agent-01", "verify_agent", {
            "github_username": "testuser123"
        }, timestamp="2026-02-12T13:00:00Z")
        run_inbox(tmp_state)

        agents = json.loads((tmp_state / "agents.json").read_text())
        agent = agents["agents"]["test-agent-01"]
        assert agent["verified"] is True
        assert agent["verified_github"] == "testuser123"
        assert agent["verified_at"] == "2026-02-12T13:00:00Z"

    def test_verify_already_verified(self, tmp_state):
        """Cannot verify an already verified agent."""
        write_delta(tmp_state / "inbox", "test-agent-01", "register_agent", {
            "name": "Test Agent", "framework": "pytest", "bio": "A test agent."
        })
        run_inbox(tmp_state)

        write_delta(tmp_state / "inbox", "test-agent-01", "verify_agent", {
            "github_username": "testuser123"
        }, timestamp="2026-02-12T13:00:00Z")
        run_inbox(tmp_state)

        write_delta(tmp_state / "inbox", "test-agent-01", "verify_agent", {
            "github_username": "otheruser"
        }, timestamp="2026-02-12T14:00:00Z")
        result = run_inbox(tmp_state)
        assert "already verified" in result.stderr.lower()

    def test_verify_unknown_agent(self, tmp_state):
        """Cannot verify a non-existent agent."""
        write_delta(tmp_state / "inbox", "nonexistent", "verify_agent", {
            "github_username": "testuser123"
        }, timestamp="2026-02-12T13:00:00Z")
        result = run_inbox(tmp_state)
        assert "not found" in result.stderr.lower()

    def test_verify_empty_username(self, tmp_state):
        """Rejects empty github_username."""
        write_delta(tmp_state / "inbox", "test-agent-01", "register_agent", {
            "name": "Test Agent", "framework": "pytest", "bio": "A test agent."
        })
        run_inbox(tmp_state)

        write_delta(tmp_state / "inbox", "test-agent-01", "verify_agent", {
            "github_username": ""
        }, timestamp="2026-02-12T13:00:00Z")
        result = run_inbox(tmp_state)
        assert "required" in result.stderr.lower()

    def test_verify_changes_logged(self, tmp_state):
        """Verification action appears in changes.json."""
        write_delta(tmp_state / "inbox", "test-agent-01", "register_agent", {
            "name": "Test Agent", "framework": "pytest", "bio": "A test agent."
        })
        run_inbox(tmp_state)

        write_delta(tmp_state / "inbox", "test-agent-01", "verify_agent", {
            "github_username": "testuser123"
        }, timestamp="2026-02-12T13:00:00Z")
        run_inbox(tmp_state)

        changes = json.loads((tmp_state / "changes.json").read_text())
        verify_changes = [c for c in changes["changes"] if c.get("type") == "verify"]
        assert len(verify_changes) >= 1
