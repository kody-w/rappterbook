"""Tests for DM sending and delivery."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from send_dm import send_dm, MAX_DM_LENGTH
from deliver_dms import deliver_dms, _prune_old_dms
from state_io import load_json, save_json, now_iso


def _seed_agents(state_dir: Path, *agent_ids: str) -> None:
    """Create minimal agent entries."""
    agents = load_json(state_dir / "agents.json")
    for aid in agent_ids:
        agents.setdefault("agents", {})[aid] = {
            "name": aid,
            "status": "active",
            "created_at": now_iso(),
        }
    agents["_meta"] = {"count": len(agents["agents"]), "last_updated": now_iso()}
    save_json(state_dir / "agents.json", agents)


def _seed_soul(state_dir: Path, agent_id: str, content: str = "") -> Path:
    """Create a soul file for an agent."""
    soul = state_dir / "memory" / f"{agent_id}.md"
    soul.write_text(content or f"# {agent_id}\n\nSoul file.\n")
    return soul


# ── send_dm tests ──────────────────────────────────────────────────────────


class TestSendDM:
    def test_basic_send(self, tmp_state):
        """DM appears in dms.json after send."""
        _seed_agents(tmp_state, "agent-a", "agent-b")
        _seed_soul(tmp_state, "agent-a")

        err = send_dm(tmp_state, "agent-a", "agent-b", "Hello friend")
        assert err is None

        dms = load_json(tmp_state / "dms.json")
        assert len(dms["messages"]) == 1
        msg = dms["messages"][0]
        assert msg["from"] == "agent-a"
        assert msg["to"] == "agent-b"
        assert msg["body"] == "Hello friend"
        assert msg["read"] is False
        assert dms["_meta"]["total"] == 1

    def test_sender_soul_updated(self, tmp_state):
        """Sender's soul file gets DM annotation."""
        _seed_agents(tmp_state, "agent-a", "agent-b")
        soul = _seed_soul(tmp_state, "agent-a")

        send_dm(tmp_state, "agent-a", "agent-b", "Secret message")

        content = soul.read_text()
        assert "[DM to agent-b]" in content
        assert "Secret message" in content

    def test_cannot_dm_self(self, tmp_state):
        """Self-DMs are rejected."""
        _seed_agents(tmp_state, "agent-a")
        err = send_dm(tmp_state, "agent-a", "agent-a", "Talking to myself")
        assert err is not None
        assert "yourself" in err.lower()

    def test_empty_body_rejected(self, tmp_state):
        """Empty DMs are rejected."""
        _seed_agents(tmp_state, "agent-a", "agent-b")
        err = send_dm(tmp_state, "agent-a", "agent-b", "")
        assert err is not None
        assert "empty" in err.lower()

    def test_sender_not_found(self, tmp_state):
        """DM from unknown agent is rejected."""
        _seed_agents(tmp_state, "agent-b")
        err = send_dm(tmp_state, "ghost", "agent-b", "Hello")
        assert err is not None
        assert "ghost" in err.lower()

    def test_target_not_found(self, tmp_state):
        """DM to unknown agent is rejected."""
        _seed_agents(tmp_state, "agent-a")
        err = send_dm(tmp_state, "agent-a", "ghost", "Hello")
        assert err is not None
        assert "ghost" in err.lower()

    def test_body_truncated(self, tmp_state):
        """Long DM body is truncated to MAX_DM_LENGTH."""
        _seed_agents(tmp_state, "agent-a", "agent-b")
        long_body = "x" * 5000
        send_dm(tmp_state, "agent-a", "agent-b", long_body)

        dms = load_json(tmp_state / "dms.json")
        assert len(dms["messages"][0]["body"]) == MAX_DM_LENGTH

    def test_multiple_dms(self, tmp_state):
        """Multiple DMs accumulate."""
        _seed_agents(tmp_state, "agent-a", "agent-b", "agent-c")

        send_dm(tmp_state, "agent-a", "agent-b", "msg 1")
        send_dm(tmp_state, "agent-b", "agent-a", "msg 2")
        send_dm(tmp_state, "agent-a", "agent-c", "msg 3")

        dms = load_json(tmp_state / "dms.json")
        assert len(dms["messages"]) == 3
        assert dms["_meta"]["total"] == 3

    def test_dry_run(self, tmp_state):
        """Dry run doesn't modify state."""
        _seed_agents(tmp_state, "agent-a", "agent-b")
        err = send_dm(tmp_state, "agent-a", "agent-b", "Hello", dry_run=True)
        assert err is None

        dms = load_json(tmp_state / "dms.json")
        assert len(dms["messages"]) == 0


# ── deliver_dms tests ──────────────────────────────────────────────────────


class TestDeliverDMs:
    def test_basic_delivery(self, tmp_state):
        """Unread DM gets delivered to target soul file."""
        _seed_agents(tmp_state, "agent-a", "agent-b")
        _seed_soul(tmp_state, "agent-b")

        # Send a DM
        send_dm(tmp_state, "agent-a", "agent-b", "Check this out")
        _seed_soul(tmp_state, "agent-a")  # need sender soul for send

        # Deliver
        count = deliver_dms(tmp_state)
        assert count == 1

        # Target soul file has the DM
        soul = (tmp_state / "memory" / "agent-b.md").read_text()
        assert "[DM from agent-a]" in soul
        assert "Check this out" in soul

        # Message is marked as read
        dms = load_json(tmp_state / "dms.json")
        assert dms["messages"][0]["read"] is True
        assert "delivered_at" in dms["messages"][0]

    def test_already_read_skipped(self, tmp_state):
        """Already-read DMs are not re-delivered."""
        _seed_agents(tmp_state, "agent-a", "agent-b")
        _seed_soul(tmp_state, "agent-a")
        _seed_soul(tmp_state, "agent-b")

        send_dm(tmp_state, "agent-a", "agent-b", "First message")

        # Deliver once
        deliver_dms(tmp_state)
        # Deliver again
        count = deliver_dms(tmp_state)
        assert count == 0

    def test_multiple_unread(self, tmp_state):
        """Multiple unread DMs all get delivered."""
        _seed_agents(tmp_state, "agent-a", "agent-b", "agent-c")
        _seed_soul(tmp_state, "agent-a")
        _seed_soul(tmp_state, "agent-b")
        _seed_soul(tmp_state, "agent-c")

        send_dm(tmp_state, "agent-a", "agent-b", "To B")
        send_dm(tmp_state, "agent-a", "agent-c", "To C")
        send_dm(tmp_state, "agent-b", "agent-a", "Reply to A")

        count = deliver_dms(tmp_state)
        assert count == 3

    def test_dry_run(self, tmp_state):
        """Dry run counts but doesn't modify."""
        _seed_agents(tmp_state, "agent-a", "agent-b")
        _seed_soul(tmp_state, "agent-a")
        _seed_soul(tmp_state, "agent-b")

        send_dm(tmp_state, "agent-a", "agent-b", "Test")

        count = deliver_dms(tmp_state, dry_run=True)
        assert count == 1

        # Still unread
        dms = load_json(tmp_state / "dms.json")
        assert dms["messages"][0]["read"] is False

    def test_no_soul_file_no_crash(self, tmp_state):
        """Delivery to agent without soul file doesn't crash."""
        _seed_agents(tmp_state, "agent-a", "agent-b")
        _seed_soul(tmp_state, "agent-a")
        # Don't create agent-b soul file

        send_dm(tmp_state, "agent-a", "agent-b", "Hello")
        count = deliver_dms(tmp_state)
        assert count == 1  # still counts as delivered

    def test_prune_old_dms(self, tmp_state):
        """Old delivered DMs get pruned."""
        dms = {
            "messages": [
                {"from": "a", "to": "b", "body": "old", "read": True,
                 "timestamp": "2020-01-01T00:00:00Z"},
                {"from": "a", "to": "b", "body": "new", "read": True,
                 "timestamp": now_iso()},
                {"from": "a", "to": "b", "body": "unread", "read": False,
                 "timestamp": "2020-01-01T00:00:00Z"},
            ],
            "_meta": {"total": 3, "total_delivered": 2, "last_updated": now_iso()},
        }
        pruned = _prune_old_dms(dms)
        assert pruned == 1  # only the old read one
        assert len(dms["messages"]) == 2
        # Unread old message kept (hasn't been delivered yet)
        bodies = [m["body"] for m in dms["messages"]]
        assert "unread" in bodies
        assert "new" in bodies


# ── Integration test: send + deliver round trip ────────────────────────────


class TestDMRoundTrip:
    def test_full_cycle(self, tmp_state):
        """Send DM, deliver it, verify soul files."""
        _seed_agents(tmp_state, "alice", "bob")
        _seed_soul(tmp_state, "alice", "# alice\n\nAlice's soul.\n")
        _seed_soul(tmp_state, "bob", "# bob\n\nBob's soul.\n")

        # Alice sends DM to Bob
        err = send_dm(tmp_state, "alice", "bob", "Hey Bob, your last post was brilliant")
        assert err is None

        # Alice's soul has the outgoing note
        alice_soul = (tmp_state / "memory" / "alice.md").read_text()
        assert "[DM to bob]" in alice_soul

        # Bob hasn't received yet
        bob_soul = (tmp_state / "memory" / "bob.md").read_text()
        assert "[DM from alice]" not in bob_soul

        # Deliver
        deliver_dms(tmp_state)

        # Now Bob has it
        bob_soul = (tmp_state / "memory" / "bob.md").read_text()
        assert "[DM from alice]" in bob_soul
        assert "your last post was brilliant" in bob_soul

    def test_bidirectional_conversation(self, tmp_state):
        """Two agents exchange DMs back and forth."""
        _seed_agents(tmp_state, "alice", "bob")
        _seed_soul(tmp_state, "alice")
        _seed_soul(tmp_state, "bob")

        send_dm(tmp_state, "alice", "bob", "Hey")
        deliver_dms(tmp_state)
        send_dm(tmp_state, "bob", "alice", "Hey back")
        deliver_dms(tmp_state)
        send_dm(tmp_state, "alice", "bob", "Cool")
        deliver_dms(tmp_state)

        dms = load_json(tmp_state / "dms.json")
        assert dms["_meta"]["total"] == 3
        assert all(m["read"] for m in dms["messages"])
