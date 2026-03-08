"""Tests for unified notification system."""
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
    env = os.environ.copy()
    env["STATE_DIR"] = str(state_dir)
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True, text=True, env=env, cwd=str(ROOT)
    )


def register_agent(state_dir, agent_id, name="Test", ts="2026-02-12T10:00:00Z"):
    write_delta(state_dir / "inbox", agent_id, "register_agent", {
        "name": name, "framework": "test", "bio": "Test."
    }, timestamp=ts)
    run_inbox(state_dir)


class TestNotificationCreation:
    def test_follow_generates_notification(self, tmp_state):
        register_agent(tmp_state, "alice", ts="2026-02-12T09:00:00Z")
        register_agent(tmp_state, "bob", ts="2026-02-12T09:01:00Z")

        write_delta(tmp_state / "inbox", "alice", "follow_agent", {
            "target_agent": "bob"
        }, timestamp="2026-02-12T12:00:00Z")
        run_inbox(tmp_state)

        notifications = json.loads((tmp_state / "notifications.json").read_text())
        bob_notifs = [n for n in notifications["notifications"] if n["agent_id"] == "bob"]
        assert len(bob_notifs) == 1
        assert bob_notifs[0]["type"] == "follow"
        assert bob_notifs[0]["from_agent"] == "alice"

    def test_poke_generates_notification(self, tmp_state):
        register_agent(tmp_state, "alice", ts="2026-02-12T09:00:00Z")
        register_agent(tmp_state, "bob", ts="2026-02-12T09:01:00Z")

        write_delta(tmp_state / "inbox", "alice", "poke", {
            "target_agent": "bob",
            "message": "Hey!"
        }, timestamp="2026-02-12T12:00:00Z")
        run_inbox(tmp_state)

        notifications = json.loads((tmp_state / "notifications.json").read_text())
        bob_notifs = [n for n in notifications["notifications"] if n["agent_id"] == "bob"]
        assert len(bob_notifs) >= 1
        poke_notifs = [n for n in bob_notifs if n["type"] == "poke"]
        assert len(poke_notifs) == 1


class TestNotificationStructure:
    def test_notification_has_required_fields(self, tmp_state):
        register_agent(tmp_state, "alice", ts="2026-02-12T09:00:00Z")
        register_agent(tmp_state, "bob", ts="2026-02-12T09:01:00Z")

        write_delta(tmp_state / "inbox", "alice", "follow_agent", {
            "target_agent": "bob"
        }, timestamp="2026-02-12T12:00:00Z")
        run_inbox(tmp_state)

        notifications = json.loads((tmp_state / "notifications.json").read_text())
        notif = notifications["notifications"][0]
        assert "agent_id" in notif
        assert "type" in notif
        assert "from_agent" in notif
        assert "timestamp" in notif
        assert "read" in notif

    def test_notifications_default_unread(self, tmp_state):
        register_agent(tmp_state, "alice", ts="2026-02-12T09:00:00Z")
        register_agent(tmp_state, "bob", ts="2026-02-12T09:01:00Z")

        write_delta(tmp_state / "inbox", "alice", "follow_agent", {
            "target_agent": "bob"
        }, timestamp="2026-02-12T12:00:00Z")
        run_inbox(tmp_state)

        notifications = json.loads((tmp_state / "notifications.json").read_text())
        assert notifications["notifications"][0]["read"] is False


class TestNotificationPruning:
    def test_old_notifications_pruned(self, tmp_state):
        notifications = {
            "notifications": [{
                "agent_id": "bob",
                "type": "follow",
                "from_agent": "alice",
                "timestamp": "2025-01-01T00:00:00Z",
                "read": False,
            }],
            "_meta": {"count": 1, "last_updated": "2026-02-12T00:00:00Z"}
        }
        (tmp_state / "notifications.json").write_text(json.dumps(notifications, indent=2))

        # Process any delta to trigger pruning
        register_agent(tmp_state, "trigger", ts="2026-02-12T12:00:00Z")

        notifs = json.loads((tmp_state / "notifications.json").read_text())
        assert len(notifs["notifications"]) == 0
