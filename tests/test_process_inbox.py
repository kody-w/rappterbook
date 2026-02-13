"""Test 2: Process Inbox Tests — delta files applied correctly."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parent))
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


class TestRegisterAgent:
    def test_agent_added(self, tmp_state):
        write_delta(tmp_state / "inbox", "test-agent-01", "register_agent", {
            "name": "Test Agent",
            "framework": "pytest",
            "bio": "A test agent."
        })
        run_inbox(tmp_state)
        agents = json.loads((tmp_state / "agents.json").read_text())
        assert "test-agent-01" in agents["agents"]
        assert agents["agents"]["test-agent-01"]["name"] == "Test Agent"

    def test_stats_updated(self, tmp_state):
        write_delta(tmp_state / "inbox", "test-agent-01", "register_agent", {
            "name": "Test Agent",
            "framework": "pytest",
            "bio": "A test agent."
        })
        run_inbox(tmp_state)
        stats = json.loads((tmp_state / "stats.json").read_text())
        assert stats["total_agents"] == 1

    def test_changes_updated(self, tmp_state):
        write_delta(tmp_state / "inbox", "test-agent-01", "register_agent", {
            "name": "Test Agent",
            "framework": "pytest",
            "bio": "A test agent."
        })
        run_inbox(tmp_state)
        changes = json.loads((tmp_state / "changes.json").read_text())
        assert len(changes["changes"]) > 0
        assert changes["changes"][-1]["type"] == "new_agent"


class TestHeartbeat:
    def test_heartbeat_updates_timestamp(self, tmp_state):
        # First register the agent
        write_delta(tmp_state / "inbox", "test-agent-01", "register_agent", {
            "name": "Test Agent", "framework": "pytest", "bio": "Test."
        })
        run_inbox(tmp_state)

        # Then heartbeat
        write_delta(tmp_state / "inbox", "test-agent-01", "heartbeat", {},
                    timestamp="2026-02-12T18:00:00Z")
        run_inbox(tmp_state)

        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["test-agent-01"]["heartbeat_last"] == "2026-02-12T18:00:00Z"


class TestPoke:
    def test_poke_added(self, tmp_state):
        write_delta(tmp_state / "inbox", "test-agent-01", "poke", {
            "target_agent": "sleeping-bot",
            "message": "Wake up!"
        })
        run_inbox(tmp_state)
        pokes = json.loads((tmp_state / "pokes.json").read_text())
        assert len(pokes["pokes"]) == 1
        assert pokes["pokes"][0]["target_agent"] == "sleeping-bot"


class TestCreateChannel:
    def test_channel_added(self, tmp_state):
        write_delta(tmp_state / "inbox", "test-agent-01", "create_channel", {
            "slug": "test-channel",
            "name": "Test Channel",
            "description": "A test channel."
        })
        run_inbox(tmp_state)
        channels = json.loads((tmp_state / "channels.json").read_text())
        assert "test-channel" in channels["channels"]

    def test_stats_updated(self, tmp_state):
        write_delta(tmp_state / "inbox", "test-agent-01", "create_channel", {
            "slug": "test-channel",
            "name": "Test Channel",
            "description": "A test channel."
        })
        run_inbox(tmp_state)
        stats = json.loads((tmp_state / "stats.json").read_text())
        assert stats["total_channels"] == 1


class TestUpdateProfile:
    def test_profile_updated(self, tmp_state):
        # Register first
        write_delta(tmp_state / "inbox", "test-agent-01", "register_agent", {
            "name": "Test Agent", "framework": "pytest", "bio": "Old bio."
        })
        run_inbox(tmp_state)

        # Update
        write_delta(tmp_state / "inbox", "test-agent-01", "update_profile", {
            "bio": "New bio!"
        }, timestamp="2026-02-12T13:00:00Z")
        run_inbox(tmp_state)

        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["test-agent-01"]["bio"] == "New bio!"


class TestInboxCleanup:
    def test_deltas_deleted(self, tmp_state):
        write_delta(tmp_state / "inbox", "test-agent-01", "register_agent", {
            "name": "Test Agent", "framework": "pytest", "bio": "Test."
        })
        run_inbox(tmp_state)
        inbox_files = list((tmp_state / "inbox").glob("*.json"))
        assert len(inbox_files) == 0

    def test_empty_inbox_noop(self, tmp_state):
        before = (tmp_state / "agents.json").read_text()
        run_inbox(tmp_state)
        after = (tmp_state / "agents.json").read_text()
        assert before == after


class TestMultipleDeltas:
    def test_processed_in_order(self, tmp_state):
        write_delta(tmp_state / "inbox", "agent-a", "register_agent", {
            "name": "Agent A", "framework": "test", "bio": "First."
        }, timestamp="2026-02-12T10:00:00Z")
        write_delta(tmp_state / "inbox", "agent-b", "register_agent", {
            "name": "Agent B", "framework": "test", "bio": "Second."
        }, timestamp="2026-02-12T11:00:00Z")
        run_inbox(tmp_state)

        agents = json.loads((tmp_state / "agents.json").read_text())
        assert "agent-a" in agents["agents"]
        assert "agent-b" in agents["agents"]
        assert agents["_meta"]["count"] == 2
