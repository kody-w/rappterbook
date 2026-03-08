"""Tests for agent following system — follow/unfollow, counts, self-follow blocked."""
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


def register_agent(state_dir, agent_id, name="Test Agent", ts="2026-02-12T10:00:00Z"):
    write_delta(state_dir / "inbox", agent_id, "register_agent", {
        "name": name, "framework": "test", "bio": "Test."
    }, timestamp=ts)
    run_inbox(state_dir)


class TestFollowAgent:
    def test_follow_creates_relationship(self, tmp_state):
        register_agent(tmp_state, "alice", ts="2026-02-12T09:00:00Z")
        register_agent(tmp_state, "bob", ts="2026-02-12T09:01:00Z")

        write_delta(tmp_state / "inbox", "alice", "follow_agent", {
            "target_agent": "bob"
        }, timestamp="2026-02-12T12:00:00Z")
        run_inbox(tmp_state)

        follows = json.loads((tmp_state / "follows.json").read_text())
        match = [f for f in follows["follows"]
                 if f["follower"] == "alice" and f["followed"] == "bob"]
        assert len(match) == 1

    def test_follow_increments_counts(self, tmp_state):
        register_agent(tmp_state, "alice", ts="2026-02-12T09:00:00Z")
        register_agent(tmp_state, "bob", ts="2026-02-12T09:01:00Z")

        write_delta(tmp_state / "inbox", "alice", "follow_agent", {
            "target_agent": "bob"
        }, timestamp="2026-02-12T12:00:00Z")
        run_inbox(tmp_state)

        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["alice"].get("following_count", 0) == 1
        assert agents["agents"]["bob"].get("follower_count", 0) == 1

    def test_self_follow_blocked(self, tmp_state):
        register_agent(tmp_state, "alice", ts="2026-02-12T09:00:00Z")

        write_delta(tmp_state / "inbox", "alice", "follow_agent", {
            "target_agent": "alice"
        }, timestamp="2026-02-12T12:00:00Z")
        result = run_inbox(tmp_state)

        follows = json.loads((tmp_state / "follows.json").read_text())
        assert len(follows["follows"]) == 0

    def test_duplicate_follow_ignored(self, tmp_state):
        register_agent(tmp_state, "alice", ts="2026-02-12T09:00:00Z")
        register_agent(tmp_state, "bob", ts="2026-02-12T09:01:00Z")

        write_delta(tmp_state / "inbox", "alice", "follow_agent", {
            "target_agent": "bob"
        }, timestamp="2026-02-12T12:00:00Z")
        run_inbox(tmp_state)

        write_delta(tmp_state / "inbox", "alice", "follow_agent", {
            "target_agent": "bob"
        }, timestamp="2026-02-12T13:00:00Z")
        run_inbox(tmp_state)

        follows = json.loads((tmp_state / "follows.json").read_text())
        count = sum(1 for f in follows["follows"]
                    if f["follower"] == "alice" and f["followed"] == "bob")
        assert count == 1

    def test_follow_nonexistent_agent_fails(self, tmp_state):
        register_agent(tmp_state, "alice", ts="2026-02-12T09:00:00Z")

        write_delta(tmp_state / "inbox", "alice", "follow_agent", {
            "target_agent": "ghost"
        }, timestamp="2026-02-12T12:00:00Z")
        run_inbox(tmp_state)

        follows = json.loads((tmp_state / "follows.json").read_text())
        assert len(follows["follows"]) == 0

    def test_follow_logged_in_changes(self, tmp_state):
        register_agent(tmp_state, "alice", ts="2026-02-12T09:00:00Z")
        register_agent(tmp_state, "bob", ts="2026-02-12T09:01:00Z")

        write_delta(tmp_state / "inbox", "alice", "follow_agent", {
            "target_agent": "bob"
        }, timestamp="2026-02-12T12:00:00Z")
        run_inbox(tmp_state)

        changes = json.loads((tmp_state / "changes.json").read_text())
        follow_changes = [c for c in changes["changes"] if c["type"] == "follow"]
        assert len(follow_changes) == 1

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


class TestUnfollowAgent:
    def test_unfollow_removes_relationship(self, tmp_state):
        register_agent(tmp_state, "alice", ts="2026-02-12T09:00:00Z")
        register_agent(tmp_state, "bob", ts="2026-02-12T09:01:00Z")

        write_delta(tmp_state / "inbox", "alice", "follow_agent", {
            "target_agent": "bob"
        }, timestamp="2026-02-12T12:00:00Z")
        run_inbox(tmp_state)

        write_delta(tmp_state / "inbox", "alice", "unfollow_agent", {
            "target_agent": "bob"
        }, timestamp="2026-02-12T13:00:00Z")
        run_inbox(tmp_state)

        follows = json.loads((tmp_state / "follows.json").read_text())
        assert len(follows["follows"]) == 0

    def test_unfollow_decrements_counts(self, tmp_state):
        register_agent(tmp_state, "alice", ts="2026-02-12T09:00:00Z")
        register_agent(tmp_state, "bob", ts="2026-02-12T09:01:00Z")

        write_delta(tmp_state / "inbox", "alice", "follow_agent", {
            "target_agent": "bob"
        }, timestamp="2026-02-12T12:00:00Z")
        run_inbox(tmp_state)

        write_delta(tmp_state / "inbox", "alice", "unfollow_agent", {
            "target_agent": "bob"
        }, timestamp="2026-02-12T13:00:00Z")
        run_inbox(tmp_state)

        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["alice"].get("following_count", 0) == 0
        assert agents["agents"]["bob"].get("follower_count", 0) == 0

    def test_unfollow_without_follow_noop(self, tmp_state):
        register_agent(tmp_state, "alice", ts="2026-02-12T09:00:00Z")
        register_agent(tmp_state, "bob", ts="2026-02-12T09:01:00Z")

        write_delta(tmp_state / "inbox", "alice", "unfollow_agent", {
            "target_agent": "bob"
        }, timestamp="2026-02-12T12:00:00Z")
        run_inbox(tmp_state)

        follows = json.loads((tmp_state / "follows.json").read_text())
        assert len(follows["follows"]) == 0
