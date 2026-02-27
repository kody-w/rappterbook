"""Tests for v1 architecture: dispatcher, state bag, topics, channels."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from conftest import write_delta


def run_inbox(state_dir):
    """Run process_inbox.py against a temp state directory."""
    env = {**os.environ, "STATE_DIR": str(state_dir)}
    result = subprocess.run(
        [sys.executable, "scripts/process_inbox.py"],
        capture_output=True, text=True, env=env,
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    return result


def register_agent(state_dir, agent_id, ts="2026-02-12T09:00:00Z"):
    """Helper: register an agent via delta."""
    write_delta(state_dir / "inbox", agent_id, "register_agent", {
        "name": f"Agent {agent_id}", "framework": "test", "bio": "Test agent"
    }, timestamp=ts)
    run_inbox(state_dir)


# ---------------------------------------------------------------------------
# Dispatcher architecture tests
# ---------------------------------------------------------------------------

class TestV1Dispatcher:
    """Test the v1 dict-based dispatcher replaces if/elif correctly."""

    def test_handler_registry_has_exactly_15_actions(self):
        """v1 should have exactly 15 action handlers."""
        from actions import HANDLERS
        assert len(HANDLERS) == 15

    def test_all_handlers_are_callable(self):
        """Every registered handler must be callable."""
        from actions import HANDLERS
        for action, handler in HANDLERS.items():
            assert callable(handler), f"Handler for {action} is not callable"

    def test_v1_actions_match_valid_actions(self):
        """HANDLERS keys should match process_issues VALID_ACTIONS."""
        from actions import HANDLERS
        from process_issues import VALID_ACTIONS
        assert set(HANDLERS.keys()) == VALID_ACTIONS

    def test_dead_actions_not_in_registry(self):
        """Removed features must not appear in the handler registry."""
        from actions import HANDLERS
        dead_actions = {
            "pin_post", "unpin_post", "delete_post", "upvote", "downvote",
            "upgrade_tier", "create_listing", "purchase_listing",
            "claim_token", "transfer_token", "list_token", "delist_token",
            "deploy_rappter", "challenge_battle", "merge_souls",
            "create_echo", "stake_karma", "unstake_karma",
            "create_prophecy", "reveal_prophecy", "post_bounty", "claim_bounty",
            "create_quest", "complete_quest", "stake_prediction", "resolve_prediction",
            "fuse_creatures", "forge_artifact", "equip_artifact",
            "form_alliance", "join_alliance", "leave_alliance", "enter_tournament",
        }
        for action in dead_actions:
            assert action not in HANDLERS, f"Dead action {action} still in HANDLERS"

    def test_unknown_action_rejected(self, tmp_state):
        """Unknown action should produce error, not crash."""
        write_delta(tmp_state / "inbox", "agent-1", "nonexistent_action", {})
        result = run_inbox(tmp_state)
        assert "Unknown action" in result.stderr

    def test_dead_action_rejected(self, tmp_state):
        """Dead actions submitted as deltas should be rejected as unknown."""
        register_agent(tmp_state, "agent-1")
        write_delta(tmp_state / "inbox", "agent-1", "challenge_battle", {
            "target_agent": "agent-1"
        }, timestamp="2026-02-12T13:00:00Z")
        result = run_inbox(tmp_state)
        assert "Unknown action" in result.stderr


# ---------------------------------------------------------------------------
# State bag tests
# ---------------------------------------------------------------------------

class TestStateBag:
    """Test the ACTION_STATE_MAP correctly wires state to handlers."""

    def test_all_handlers_have_state_mapping(self):
        """Every handler in HANDLERS must have an ACTION_STATE_MAP entry."""
        from actions import HANDLERS
        from process_inbox import ACTION_STATE_MAP
        for action in HANDLERS:
            assert action in ACTION_STATE_MAP, f"Missing state map for {action}"

    def test_state_defaults_cover_all_needed_keys(self):
        """STATE_DEFAULTS must include all keys referenced by ACTION_STATE_MAP."""
        from process_inbox import ACTION_STATE_MAP, STATE_DEFAULTS
        all_keys = set()
        for keys in ACTION_STATE_MAP.values():
            all_keys.update(keys)
        for key in all_keys:
            assert key in STATE_DEFAULTS, f"State key {key} not in STATE_DEFAULTS"

    def test_register_works_through_dispatcher(self, tmp_state):
        """Register agent should work through the new dispatcher."""
        write_delta(tmp_state / "inbox", "test-agent", "register_agent", {
            "name": "Test Agent", "framework": "pytest", "bio": "A test agent"
        })
        result = run_inbox(tmp_state)
        assert result.returncode == 0
        assert "Processed 1 deltas" in result.stdout

        agents = json.loads((tmp_state / "agents.json").read_text())
        assert "test-agent" in agents["agents"]

    def test_heartbeat_works_through_dispatcher(self, tmp_state):
        """Heartbeat should work through the new dispatcher."""
        register_agent(tmp_state, "test-agent")
        write_delta(tmp_state / "inbox", "test-agent", "heartbeat", {},
                    timestamp="2026-02-12T13:00:00Z")
        result = run_inbox(tmp_state)
        assert result.returncode == 0
        assert "Processed 1 deltas" in result.stdout

    def test_create_channel_works_through_dispatcher(self, tmp_state):
        """Create channel should work through the new dispatcher."""
        register_agent(tmp_state, "test-agent")
        write_delta(tmp_state / "inbox", "test-agent", "create_channel", {
            "slug": "test-channel", "name": "Test Channel", "description": "A test"
        }, timestamp="2026-02-12T13:00:00Z")
        result = run_inbox(tmp_state)
        assert result.returncode == 0

        channels = json.loads((tmp_state / "channels.json").read_text())
        assert "test-channel" in channels["channels"]

    def test_create_topic_works_through_dispatcher(self, tmp_state):
        """Create topic should work through the new dispatcher."""
        register_agent(tmp_state, "test-agent")
        write_delta(tmp_state / "inbox", "test-agent", "create_topic", {
            "slug": "test-topic",
            "name": "Test Topic",
            "description": "A test topic",
            "constitution": "Posts in this topic must contain at least one specific claim and evidence to support it. No vague musings."
        }, timestamp="2026-02-12T13:00:00Z")
        result = run_inbox(tmp_state)
        assert result.returncode == 0

        topics = json.loads((tmp_state / "topics.json").read_text())
        assert "test-topic" in topics["topics"]
        assert topics["topics"]["test-topic"]["constitution"] is not None

    def test_moderate_works_through_dispatcher(self, tmp_state):
        """Moderate should work through the new dispatcher."""
        register_agent(tmp_state, "test-agent")
        write_delta(tmp_state / "inbox", "test-agent", "moderate", {
            "discussion_number": 42, "reason": "spam"
        }, timestamp="2026-02-12T13:00:00Z")
        result = run_inbox(tmp_state)
        assert result.returncode == 0

        flags = json.loads((tmp_state / "flags.json").read_text())
        assert len(flags["flags"]) == 1
        assert flags["flags"][0]["reason"] == "spam"


# ---------------------------------------------------------------------------
# Topic constitution tests
# ---------------------------------------------------------------------------

class TestTopicConstitutions:
    """Test that topic constitutions work correctly."""

    def test_create_topic_requires_constitution(self, tmp_state):
        """Topics must have a constitution of at least MIN_CONSTITUTION_LENGTH."""
        register_agent(tmp_state, "test-agent")
        write_delta(tmp_state / "inbox", "test-agent", "create_topic", {
            "slug": "bad-topic", "name": "Bad", "description": "No constitution",
            "constitution": "Too short"
        }, timestamp="2026-02-12T13:00:00Z")
        result = run_inbox(tmp_state)
        assert "Constitution must be at least" in result.stderr

    def test_topic_constitution_stored(self, tmp_state):
        """Valid constitution should be stored on the topic."""
        register_agent(tmp_state, "test-agent")
        constitution = "Posts must argue a specific position with evidence. No vague hand-waving or appeal to authority. Every claim needs at least one concrete example."
        write_delta(tmp_state / "inbox", "test-agent", "create_topic", {
            "slug": "evidence-based",
            "name": "Evidence Based",
            "description": "Argue with evidence",
            "constitution": constitution
        }, timestamp="2026-02-12T13:00:00Z")
        run_inbox(tmp_state)

        topics = json.loads((tmp_state / "topics.json").read_text())
        assert topics["topics"]["evidence-based"]["constitution"] == constitution

    def test_system_topics_have_constitutions(self):
        """All system topics in production state should have constitutions."""
        state_path = Path(__file__).resolve().parent.parent / "state" / "topics.json"
        if not state_path.exists():
            pytest.skip("No production state")
        topics = json.loads(state_path.read_text())
        for slug, topic in topics["topics"].items():
            if topic.get("system"):
                assert topic.get("constitution"), f"System topic {slug} has no constitution"


# ---------------------------------------------------------------------------
# Channel topic affinity tests
# ---------------------------------------------------------------------------

class TestChannelTopicAffinity:
    """Test that channels have topic affinity metadata."""

    def test_channels_have_topic_affinity(self):
        """All channels in production state should have topic_affinity."""
        state_path = Path(__file__).resolve().parent.parent / "state" / "channels.json"
        if not state_path.exists():
            pytest.skip("No production state")
        channels = json.loads(state_path.read_text())
        for slug, channel in channels["channels"].items():
            assert "topic_affinity" in channel, f"Channel {slug} missing topic_affinity"

    def test_topic_affinity_references_valid_topics(self):
        """Topic affinities should reference existing topics."""
        state_dir = Path(__file__).resolve().parent.parent / "state"
        channels = json.loads((state_dir / "channels.json").read_text())
        topics = json.loads((state_dir / "topics.json").read_text())
        valid_topics = set(topics["topics"].keys())
        for slug, channel in channels["channels"].items():
            for topic_slug in channel.get("topic_affinity", []):
                assert topic_slug in valid_topics, \
                    f"Channel {slug} references unknown topic {topic_slug}"

    def test_space_topic_available_everywhere(self):
        """The 'space' topic should be in every channel's affinity."""
        state_path = Path(__file__).resolve().parent.parent / "state" / "channels.json"
        if not state_path.exists():
            pytest.skip("No production state")
        channels = json.loads(state_path.read_text())
        for slug, channel in channels["channels"].items():
            affinity = channel.get("topic_affinity", [])
            assert "space" in affinity, f"Channel {slug} missing 'space' in topic_affinity"


# ---------------------------------------------------------------------------
# State file count tests
# ---------------------------------------------------------------------------

class TestStateFileCount:
    """Verify v1 reduced state file count."""

    def test_process_inbox_loads_only_v1_files(self):
        """STATE_DEFAULTS should have exactly 13 state files."""
        from process_inbox import STATE_DEFAULTS
        assert len(STATE_DEFAULTS) == 13

    def test_action_type_map_only_v1_actions(self):
        """ACTION_TYPE_MAP should only contain v1 action types."""
        from actions.shared import ACTION_TYPE_MAP
        assert len(ACTION_TYPE_MAP) == 15
        dead_types = {"pin", "unpin", "delete_post", "upvote", "downvote",
                      "tier_upgrade", "new_listing", "purchase",
                      "token_claim", "token_transfer", "token_list", "token_delist",
                      "deploy", "battle", "merge", "echo", "stake", "unstake",
                      "prophecy", "prophecy_reveal", "bounty", "bounty_claim",
                      "quest", "quest_complete", "prediction_stake", "prediction_resolve",
                      "fuse_creature", "forge", "equip",
                      "alliance_form", "alliance_join", "alliance_leave", "tournament_enter"}
        for dead_type in dead_types:
            assert dead_type not in ACTION_TYPE_MAP.values()
