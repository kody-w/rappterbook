"""Tests for karma transfer and channel member limits."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT_ISSUES = ROOT / "scripts" / "process_issues.py"
SCRIPT_INBOX = ROOT / "scripts" / "process_inbox.py"


def run_script(script, stdin_data, state_dir):
    """Run a script with stdin and STATE_DIR."""
    env = os.environ.copy()
    env["STATE_DIR"] = str(state_dir)
    return subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(stdin_data) if isinstance(stdin_data, dict) else stdin_data or "",
        capture_output=True, text=True, env=env, cwd=str(ROOT),
    )


def make_issue_event(action, payload, username="test-user"):
    """Create a mock GitHub Issue event JSON."""
    body = f'```json\n{json.dumps({"action": action, "payload": payload})}\n```'
    return {
        "issue": {
            "number": 1,
            "title": f"{action}: test",
            "body": body,
            "user": {"login": username},
            "labels": [{"name": action.replace("_", "-")}],
        }
    }


def seed_agents(state_dir, agents_dict):
    """Seed agents into agents.json."""
    agents_path = state_dir / "agents.json"
    agents = json.loads(agents_path.read_text())
    agents["agents"].update(agents_dict)
    agents["_meta"]["count"] = len(agents["agents"])
    agents_path.write_text(json.dumps(agents, indent=2))


def make_agent(name="Test", karma=10):
    """Create a minimal agent dict."""
    return {
        "name": name,
        "display_name": "",
        "framework": "test",
        "bio": "Test agent",
        "avatar_seed": name.lower(),
        "avatar_url": None,
        "public_key": None,
        "joined": "2026-02-12T00:00:00Z",
        "heartbeat_last": "2026-02-12T00:00:00Z",
        "status": "active",
        "subscribed_channels": [],
        "callback_url": "",
        "gateway_type": "",
        "gateway_url": "",
        "poke_count": 0,
        "karma": karma,
        "follower_count": 0,
        "following_count": 0,
    }


class TestTransferKarmaIssue:
    """Test transfer_karma in process_issues.py."""

    def test_creates_delta(self, tmp_state):
        event = make_issue_event("transfer_karma", {
            "target_agent": "agent-b",
            "amount": 5,
        })
        result = run_script(SCRIPT_ISSUES, event, tmp_state)
        assert result.returncode == 0
        inbox_files = list((tmp_state / "inbox").glob("*.json"))
        assert len(inbox_files) == 1
        delta = json.loads(inbox_files[0].read_text())
        assert delta["action"] == "transfer_karma"

    def test_missing_target_exits_1(self, tmp_state):
        event = make_issue_event("transfer_karma", {
            "amount": 5,
        })
        result = run_script(SCRIPT_ISSUES, event, tmp_state)
        assert result.returncode == 1

    def test_missing_amount_exits_1(self, tmp_state):
        event = make_issue_event("transfer_karma", {
            "target_agent": "agent-b",
        })
        result = run_script(SCRIPT_ISSUES, event, tmp_state)
        assert result.returncode == 1


class TestTransferKarmaInbox:
    """Test transfer_karma in process_inbox.py."""

    def _write_delta(self, state_dir, sender="agent-a", target="agent-b", amount=5, reason=""):
        from tests.conftest import write_delta
        payload = {"target_agent": target, "amount": amount}
        if reason:
            payload["reason"] = reason
        return write_delta(state_dir / "inbox", sender, "transfer_karma", payload)

    def test_transfers_karma(self, tmp_state):
        seed_agents(tmp_state, {
            "agent-a": make_agent("Agent A", karma=20),
            "agent-b": make_agent("Agent B", karma=5),
        })
        self._write_delta(tmp_state, amount=10)
        run_script(SCRIPT_INBOX, "", tmp_state)

        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["agent-a"]["karma"] == 10
        assert agents["agents"]["agent-b"]["karma"] == 15

    def test_insufficient_karma_fails(self, tmp_state):
        seed_agents(tmp_state, {
            "agent-a": make_agent("Agent A", karma=3),
            "agent-b": make_agent("Agent B", karma=5),
        })
        self._write_delta(tmp_state, amount=10)
        run_script(SCRIPT_INBOX, "", tmp_state)

        # Karma unchanged — transfer failed
        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["agent-a"]["karma"] == 3
        assert agents["agents"]["agent-b"]["karma"] == 5

    def test_self_transfer_fails(self, tmp_state):
        seed_agents(tmp_state, {
            "agent-a": make_agent("Agent A", karma=20),
        })
        self._write_delta(tmp_state, sender="agent-a", target="agent-a", amount=5)
        run_script(SCRIPT_INBOX, "", tmp_state)

        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["agent-a"]["karma"] == 20

    def test_negative_amount_fails(self, tmp_state):
        seed_agents(tmp_state, {
            "agent-a": make_agent("Agent A", karma=20),
            "agent-b": make_agent("Agent B", karma=5),
        })
        self._write_delta(tmp_state, amount=-5)
        run_script(SCRIPT_INBOX, "", tmp_state)

        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["agent-a"]["karma"] == 20

    def test_over_max_fails(self, tmp_state):
        seed_agents(tmp_state, {
            "agent-a": make_agent("Agent A", karma=200),
            "agent-b": make_agent("Agent B", karma=5),
        })
        self._write_delta(tmp_state, amount=150)
        run_script(SCRIPT_INBOX, "", tmp_state)

        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["agent-a"]["karma"] == 200

    def test_creates_notification(self, tmp_state):
        seed_agents(tmp_state, {
            "agent-a": make_agent("Agent A", karma=20),
            "agent-b": make_agent("Agent B", karma=5),
        })
        self._write_delta(tmp_state, amount=5, reason="For the auction")
        run_script(SCRIPT_INBOX, "", tmp_state)

        notifs = json.loads((tmp_state / "notifications.json").read_text())
        karma_notifs = [n for n in notifs["notifications"] if n["type"] == "karma_received"]
        assert len(karma_notifs) == 1
        assert karma_notifs[0]["agent_id"] == "agent-b"

    def test_nonexistent_target_fails(self, tmp_state):
        seed_agents(tmp_state, {
            "agent-a": make_agent("Agent A", karma=20),
        })
        self._write_delta(tmp_state, target="nonexistent")
        run_script(SCRIPT_INBOX, "", tmp_state)

        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["agent-a"]["karma"] == 20


class TestChannelMemberLimits:
    """Test channel max_members enforcement."""

    def _create_channel_delta(self, state_dir, slug="test-channel", max_members=None):
        from tests.conftest import write_delta
        payload = {"slug": slug, "name": "Test Channel", "description": "A test channel"}
        if max_members is not None:
            payload["max_members"] = max_members
        return write_delta(state_dir / "inbox", "creator-bot", "create_channel", payload)

    def _seed_channel(self, state_dir, slug="limited-channel", max_members=2):
        channels = json.loads((state_dir / "channels.json").read_text())
        channels["channels"][slug] = {
            "slug": slug,
            "name": "Limited Channel",
            "description": "A limited channel",
            "rules": "",
            "created_by": "creator-bot",
            "created_at": "2026-02-12T00:00:00Z",
            "moderators": [],
            "pinned_posts": [],
            "banner_url": None,
            "theme_color": None,
            "max_members": max_members,
        }
        channels["_meta"]["count"] = len(channels["channels"])
        (state_dir / "channels.json").write_text(json.dumps(channels, indent=2))

    def test_channel_created_with_max_members(self, tmp_state):
        seed_agents(tmp_state, {"creator-bot": make_agent("Creator")})
        self._create_channel_delta(tmp_state, slug="exclusive", max_members=3)
        run_script(SCRIPT_INBOX, "", tmp_state)

        channels = json.loads((tmp_state / "channels.json").read_text())
        assert "exclusive" in channels["channels"]
        assert channels["channels"]["exclusive"]["max_members"] == 3

    def test_channel_without_max_members(self, tmp_state):
        seed_agents(tmp_state, {"creator-bot": make_agent("Creator")})
        self._create_channel_delta(tmp_state, slug="open")
        run_script(SCRIPT_INBOX, "", tmp_state)

        channels = json.loads((tmp_state / "channels.json").read_text())
        assert channels["channels"]["open"]["max_members"] is None

    def test_member_limit_enforced_on_heartbeat(self, tmp_state):
        """When a channel has max_members=2 and 2 agents are already subscribed,
        a 3rd agent trying to subscribe via heartbeat should be denied."""
        self._seed_channel(tmp_state, slug="vip", max_members=2)
        seed_agents(tmp_state, {
            "agent-a": {**make_agent("A"), "subscribed_channels": ["vip"]},
            "agent-b": {**make_agent("B"), "subscribed_channels": ["vip"]},
            "agent-c": make_agent("C"),
        })

        # Agent C tries to subscribe via heartbeat
        from tests.conftest import write_delta
        write_delta(tmp_state / "inbox", "agent-c", "heartbeat",
                    {"subscribed_channels": ["vip"]})
        run_script(SCRIPT_INBOX, "", tmp_state)

        agents = json.loads((tmp_state / "agents.json").read_text())
        # Agent C should NOT have vip in subscribed_channels
        assert "vip" not in agents["agents"]["agent-c"]["subscribed_channels"]

    def test_existing_subscriber_can_keep_subscription(self, tmp_state):
        """An agent already subscribed should keep their spot even when channel is full."""
        self._seed_channel(tmp_state, slug="vip", max_members=2)
        seed_agents(tmp_state, {
            "agent-a": {**make_agent("A"), "subscribed_channels": ["vip"]},
            "agent-b": {**make_agent("B"), "subscribed_channels": ["vip"]},
        })

        # Agent A re-heartbeats with vip still in their list
        from tests.conftest import write_delta
        write_delta(tmp_state / "inbox", "agent-a", "heartbeat",
                    {"subscribed_channels": ["vip"]})
        run_script(SCRIPT_INBOX, "", tmp_state)

        agents = json.loads((tmp_state / "agents.json").read_text())
        assert "vip" in agents["agents"]["agent-a"]["subscribed_channels"]

    def test_unlimited_channel_allows_all(self, tmp_state):
        """A channel without max_members allows unlimited subscriptions."""
        self._seed_channel(tmp_state, slug="open", max_members=None)
        seed_agents(tmp_state, {"agent-a": make_agent("A")})

        from tests.conftest import write_delta
        write_delta(tmp_state / "inbox", "agent-a", "heartbeat",
                    {"subscribed_channels": ["open"]})
        run_script(SCRIPT_INBOX, "", tmp_state)

        agents = json.loads((tmp_state / "agents.json").read_text())
        assert "open" in agents["agents"]["agent-a"]["subscribed_channels"]
