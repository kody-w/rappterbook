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
        # Register target agent first so poke validation passes
        write_delta(tmp_state / "inbox", "sleeping-bot", "register_agent", {
            "name": "Sleepy", "framework": "test", "bio": "Zzz."
        }, timestamp="2026-02-12T09:00:00Z")
        run_inbox(tmp_state)

        write_delta(tmp_state / "inbox", "test-agent-01", "poke", {
            "target_agent": "sleeping-bot",
            "message": "Wake up!"
        })
        run_inbox(tmp_state)
        pokes = json.loads((tmp_state / "pokes.json").read_text())
        assert len(pokes["pokes"]) == 1
        assert pokes["pokes"][0]["target_agent"] == "sleeping-bot"

    def test_poke_count_incremented(self, tmp_state):
        # Register target agent first
        write_delta(tmp_state / "inbox", "target-bot", "register_agent", {
            "name": "Target", "framework": "test", "bio": "Test."
        }, timestamp="2026-02-12T10:00:00Z")
        run_inbox(tmp_state)

        # Poke the target
        write_delta(tmp_state / "inbox", "poker-bot", "poke", {
            "target_agent": "target-bot",
            "message": "Hey!"
        }, timestamp="2026-02-12T11:00:00Z")
        run_inbox(tmp_state)

        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["target-bot"]["poke_count"] == 1


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


class TestModerate:
    def test_flag_added(self, tmp_state):
        write_delta(tmp_state / "inbox", "test-agent-01", "moderate", {
            "discussion_number": 42,
            "reason": "spam",
            "detail": "Looks like automated spam"
        })
        run_inbox(tmp_state)
        flags = json.loads((tmp_state / "flags.json").read_text())
        assert len(flags["flags"]) == 1
        assert flags["flags"][0]["discussion_number"] == 42
        assert flags["flags"][0]["reason"] == "spam"
        assert flags["flags"][0]["flagged_by"] == "test-agent-01"
        assert flags["flags"][0]["status"] == "pending"

    def test_flag_logged_in_changes(self, tmp_state):
        write_delta(tmp_state / "inbox", "test-agent-01", "moderate", {
            "discussion_number": 99,
            "reason": "off-topic"
        })
        run_inbox(tmp_state)
        changes = json.loads((tmp_state / "changes.json").read_text())
        flag_changes = [c for c in changes["changes"] if c["type"] == "flag"]
        assert len(flag_changes) == 1
        assert flag_changes[0]["discussion"] == 99

    def test_invalid_reason_rejected(self, tmp_state):
        write_delta(tmp_state / "inbox", "test-agent-01", "moderate", {
            "discussion_number": 42,
            "reason": "i-dont-like-it"
        })
        result = run_inbox(tmp_state)
        flags = json.loads((tmp_state / "flags.json").read_text())
        assert len(flags["flags"]) == 0

    def test_multiple_flags_accumulate(self, tmp_state):
        write_delta(tmp_state / "inbox", "agent-a", "moderate", {
            "discussion_number": 10,
            "reason": "spam"
        }, timestamp="2026-02-12T10:00:00Z")
        write_delta(tmp_state / "inbox", "agent-b", "moderate", {
            "discussion_number": 10,
            "reason": "harmful"
        }, timestamp="2026-02-12T11:00:00Z")
        run_inbox(tmp_state)
        flags = json.loads((tmp_state / "flags.json").read_text())
        assert len(flags["flags"]) == 2
        assert flags["_meta"]["count"] == 2


class TestInputSanitization:
    """Security tests: HTML stripping, length limits, URL validation, slug validation."""

    def test_html_stripped_from_name(self, tmp_state):
        write_delta(tmp_state / "inbox", "xss-agent", "register_agent", {
            "name": '<img src=x onerror=alert(1)>',
            "framework": "test",
            "bio": "Normal bio."
        })
        run_inbox(tmp_state)
        agents = json.loads((tmp_state / "agents.json").read_text())
        name = agents["agents"]["xss-agent"]["name"]
        assert "<" not in name
        assert ">" not in name

    def test_html_stripped_from_bio(self, tmp_state):
        write_delta(tmp_state / "inbox", "xss-agent", "register_agent", {
            "name": "Safe Name",
            "framework": "test",
            "bio": '<script>alert("xss")</script>Normal text'
        })
        run_inbox(tmp_state)
        agents = json.loads((tmp_state / "agents.json").read_text())
        bio = agents["agents"]["xss-agent"]["bio"]
        assert "<script>" not in bio
        assert "Normal text" in bio

    def test_name_truncated_to_max_length(self, tmp_state):
        write_delta(tmp_state / "inbox", "long-name", "register_agent", {
            "name": "A" * 200,
            "framework": "test",
            "bio": "Test."
        })
        run_inbox(tmp_state)
        agents = json.loads((tmp_state / "agents.json").read_text())
        assert len(agents["agents"]["long-name"]["name"]) == 64

    def test_bio_truncated_to_max_length(self, tmp_state):
        write_delta(tmp_state / "inbox", "long-bio", "register_agent", {
            "name": "Agent",
            "framework": "test",
            "bio": "B" * 1000
        })
        run_inbox(tmp_state)
        agents = json.loads((tmp_state / "agents.json").read_text())
        assert len(agents["agents"]["long-bio"]["bio"]) == 500

    def test_callback_url_must_be_https(self, tmp_state):
        write_delta(tmp_state / "inbox", "bad-url", "register_agent", {
            "name": "Agent",
            "framework": "test",
            "bio": "Test.",
            "callback_url": "javascript:alert(1)"
        })
        run_inbox(tmp_state)
        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["bad-url"]["callback_url"] is None

    def test_callback_url_https_allowed(self, tmp_state):
        write_delta(tmp_state / "inbox", "good-url", "register_agent", {
            "name": "Agent",
            "framework": "test",
            "bio": "Test.",
            "callback_url": "https://example.com/repo"
        })
        run_inbox(tmp_state)
        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["good-url"]["callback_url"] == "https://example.com/repo"

    def test_channel_slug_meta_rejected(self, tmp_state):
        write_delta(tmp_state / "inbox", "attacker", "create_channel", {
            "slug": "_meta",
            "name": "Evil Channel",
            "description": "Overwrite metadata"
        })
        run_inbox(tmp_state)
        channels = json.loads((tmp_state / "channels.json").read_text())
        assert "_meta" not in channels["channels"]

    def test_channel_slug_special_chars_rejected(self, tmp_state):
        write_delta(tmp_state / "inbox", "attacker", "create_channel", {
            "slug": "../etc/passwd",
            "name": "Path Traversal",
            "description": "Evil"
        })
        run_inbox(tmp_state)
        channels = json.loads((tmp_state / "channels.json").read_text())
        assert len(channels["channels"]) == 0

    def test_channel_slug_valid_accepted(self, tmp_state):
        write_delta(tmp_state / "inbox", "good-agent", "create_channel", {
            "slug": "my-channel-1",
            "name": "Good Channel",
            "description": "Legit channel"
        })
        run_inbox(tmp_state)
        channels = json.loads((tmp_state / "channels.json").read_text())
        assert "my-channel-1" in channels["channels"]

    def test_update_profile_sanitizes_name(self, tmp_state):
        write_delta(tmp_state / "inbox", "agent-1", "register_agent", {
            "name": "Original", "framework": "test", "bio": "Test."
        })
        run_inbox(tmp_state)
        write_delta(tmp_state / "inbox", "agent-1", "update_profile", {
            "name": '<b onmouseover=alert(1)>evil</b>'
        }, timestamp="2026-02-12T13:00:00Z")
        run_inbox(tmp_state)
        agents = json.loads((tmp_state / "agents.json").read_text())
        name = agents["agents"]["agent-1"]["name"]
        assert "<" not in name
        assert "evil" in name

    def test_update_profile_validates_callback_url(self, tmp_state):
        write_delta(tmp_state / "inbox", "agent-1", "register_agent", {
            "name": "Agent", "framework": "test", "bio": "Test."
        })
        run_inbox(tmp_state)
        write_delta(tmp_state / "inbox", "agent-1", "update_profile", {
            "callback_url": "http://evil.com"
        }, timestamp="2026-02-12T13:00:00Z")
        run_inbox(tmp_state)
        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["agent-1"]["callback_url"] is None

    def test_channel_html_stripped_from_description(self, tmp_state):
        write_delta(tmp_state / "inbox", "agent-1", "create_channel", {
            "slug": "safe-channel",
            "name": "Channel",
            "description": '<img src=x onerror=alert(1)>Nice channel'
        })
        run_inbox(tmp_state)
        channels = json.loads((tmp_state / "channels.json").read_text())
        desc = channels["channels"]["safe-channel"]["description"]
        assert "<" not in desc
        assert "Nice channel" in desc


class TestRateLimiting:
    """Security tests: per-agent rate limiting."""

    def test_agent_limited_to_max_actions(self, tmp_state):
        # Submit 12 heartbeats — only 10 should process (need agent first)
        write_delta(tmp_state / "inbox", "flood-agent", "register_agent", {
            "name": "Flooder", "framework": "test", "bio": "Test."
        }, timestamp="2026-02-12T00:00:00Z")
        run_inbox(tmp_state)

        for i in range(12):
            write_delta(tmp_state / "inbox", "flood-agent", "heartbeat", {},
                        timestamp=f"2026-02-12T01:{i:02d}:00Z")
        result = run_inbox(tmp_state)
        assert "Rate limit" in result.stderr

    def test_different_agents_have_separate_limits(self, tmp_state):
        # Register two agents
        write_delta(tmp_state / "inbox", "agent-a", "register_agent", {
            "name": "A", "framework": "test", "bio": "Test."
        }, timestamp="2026-02-12T00:00:00Z")
        write_delta(tmp_state / "inbox", "agent-b", "register_agent", {
            "name": "B", "framework": "test", "bio": "Test."
        }, timestamp="2026-02-12T00:00:01Z")
        run_inbox(tmp_state)

        # 5 heartbeats each — both under limit
        for i in range(5):
            write_delta(tmp_state / "inbox", "agent-a", "heartbeat", {},
                        timestamp=f"2026-02-12T01:{i:02d}:00Z")
            write_delta(tmp_state / "inbox", "agent-b", "heartbeat", {},
                        timestamp=f"2026-02-12T01:{i:02d}:01Z")
        result = run_inbox(tmp_state)
        assert "Rate limit" not in result.stderr


class TestPruning:
    """Security tests: pokes and flags are pruned."""

    def test_old_pokes_pruned(self, tmp_state):
        # Write a poke with an old timestamp directly into state
        pokes = json.loads((tmp_state / "pokes.json").read_text())
        pokes["pokes"].append({
            "from_agent": "old-agent",
            "target_agent": "someone",
            "message": "ancient poke",
            "timestamp": "2025-01-01T00:00:00Z"
        })
        pokes["_meta"]["count"] = 1
        (tmp_state / "pokes.json").write_text(json.dumps(pokes, indent=2))

        # Process any delta to trigger pruning
        write_delta(tmp_state / "inbox", "trigger-agent", "register_agent", {
            "name": "Trigger", "framework": "test", "bio": "Test."
        })
        run_inbox(tmp_state)

        pokes_after = json.loads((tmp_state / "pokes.json").read_text())
        assert len(pokes_after["pokes"]) == 0

    def test_recent_pokes_kept(self, tmp_state):
        # Register target agent first so poke validation passes
        write_delta(tmp_state / "inbox", "target", "register_agent", {
            "name": "Target", "framework": "test", "bio": "Test."
        }, timestamp="2026-02-12T09:00:00Z")
        run_inbox(tmp_state)

        write_delta(tmp_state / "inbox", "poker", "poke", {
            "target_agent": "target",
            "message": "recent poke"
        })
        run_inbox(tmp_state)

        pokes = json.loads((tmp_state / "pokes.json").read_text())
        assert len(pokes["pokes"]) == 1

    def test_old_flags_pruned(self, tmp_state):
        flags = json.loads((tmp_state / "flags.json").read_text())
        flags["flags"].append({
            "discussion_number": 1,
            "flagged_by": "old-agent",
            "reason": "spam",
            "detail": "",
            "status": "pending",
            "timestamp": "2025-01-01T00:00:00Z"
        })
        flags["_meta"]["count"] = 1
        (tmp_state / "flags.json").write_text(json.dumps(flags, indent=2))

        write_delta(tmp_state / "inbox", "trigger-agent", "register_agent", {
            "name": "Trigger", "framework": "test", "bio": "Test."
        })
        run_inbox(tmp_state)

        flags_after = json.loads((tmp_state / "flags.json").read_text())
        assert len(flags_after["flags"]) == 0


class TestSubscribedChannelsValidation:
    """Security tests: subscribed_channels type validation."""

    def test_non_list_rejected(self, tmp_state):
        write_delta(tmp_state / "inbox", "bad-agent", "register_agent", {
            "name": "Bad", "framework": "test", "bio": "Test.",
            "subscribed_channels": "not-a-list"
        })
        run_inbox(tmp_state)
        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["bad-agent"]["subscribed_channels"] == []

    def test_dict_rejected(self, tmp_state):
        write_delta(tmp_state / "inbox", "proto-agent", "register_agent", {
            "name": "Proto", "framework": "test", "bio": "Test.",
            "subscribed_channels": {"__proto__": "polluted"}
        })
        run_inbox(tmp_state)
        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["proto-agent"]["subscribed_channels"] == []

    def test_non_string_items_filtered(self, tmp_state):
        write_delta(tmp_state / "inbox", "mixed-agent", "register_agent", {
            "name": "Mixed", "framework": "test", "bio": "Test.",
            "subscribed_channels": ["general", 42, None, "code"]
        })
        run_inbox(tmp_state)
        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["mixed-agent"]["subscribed_channels"] == ["general", "code"]

    def test_valid_list_accepted(self, tmp_state):
        write_delta(tmp_state / "inbox", "good-agent", "register_agent", {
            "name": "Good", "framework": "test", "bio": "Test.",
            "subscribed_channels": ["general", "code", "meta"]
        })
        run_inbox(tmp_state)
        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["good-agent"]["subscribed_channels"] == ["general", "code", "meta"]

    def test_heartbeat_validates_channels(self, tmp_state):
        write_delta(tmp_state / "inbox", "agent-1", "register_agent", {
            "name": "A", "framework": "test", "bio": "Test."
        })
        run_inbox(tmp_state)

        write_delta(tmp_state / "inbox", "agent-1", "heartbeat", {
            "subscribed_channels": {"evil": True}
        }, timestamp="2026-02-12T13:00:00Z")
        run_inbox(tmp_state)
        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["agent-1"]["subscribed_channels"] == []

    def test_update_profile_validates_channels(self, tmp_state):
        write_delta(tmp_state / "inbox", "agent-1", "register_agent", {
            "name": "A", "framework": "test", "bio": "Test.",
            "subscribed_channels": ["general"]
        })
        run_inbox(tmp_state)

        write_delta(tmp_state / "inbox", "agent-1", "update_profile", {
            "subscribed_channels": 999
        }, timestamp="2026-02-12T13:00:00Z")
        run_inbox(tmp_state)
        agents = json.loads((tmp_state / "agents.json").read_text())
        assert agents["agents"]["agent-1"]["subscribed_channels"] == []
