"""Tests for the create_topic action — issue validation, state mutation, rejections."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "scripts"))

from conftest import write_delta

SCRIPT = ROOT / "scripts" / "process_inbox.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_inbox(state_dir):
    """Run process_inbox.py as a subprocess with the given state directory."""
    env = os.environ.copy()
    env["STATE_DIR"] = str(state_dir)
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True, text=True, env=env, cwd=str(ROOT)
    )


def load_topics(tmp_state):
    """Load topics.json from the tmp state dir."""
    return json.loads((tmp_state / "topics.json").read_text())


def load_stats(tmp_state):
    """Load stats.json from the tmp state dir."""
    return json.loads((tmp_state / "stats.json").read_text())


def load_changes(tmp_state):
    """Load changes.json from the tmp state dir."""
    return json.loads((tmp_state / "changes.json").read_text())


# ---------------------------------------------------------------------------
# Issue validation tests
# ---------------------------------------------------------------------------

class TestCreateTopicIssueValidation:
    def test_valid_action_accepted(self):
        from process_issues import validate_action
        data = {
            "action": "create_topic",
            "payload": {"slug": "my-topic", "name": "My Topic", "description": "A custom topic"},
        }
        assert validate_action(data) is None

    def test_missing_slug_rejected(self):
        from process_issues import validate_action
        data = {
            "action": "create_topic",
            "payload": {"name": "My Topic", "description": "A custom topic"},
        }
        error = validate_action(data)
        assert error is not None
        assert "slug" in error

    def test_missing_name_rejected(self):
        from process_issues import validate_action
        data = {
            "action": "create_topic",
            "payload": {"slug": "my-topic", "description": "A custom topic"},
        }
        error = validate_action(data)
        assert error is not None
        assert "name" in error

    def test_missing_description_rejected(self):
        from process_issues import validate_action
        data = {
            "action": "create_topic",
            "payload": {"slug": "my-topic", "name": "My Topic"},
        }
        error = validate_action(data)
        assert error is not None
        assert "description" in error

    def test_delta_created_in_inbox(self, tmp_state):
        data = {
            "action": "create_topic",
            "payload": {"slug": "my-topic", "name": "My Topic", "description": "Desc"},
        }
        from process_issues import validate_action
        error = validate_action(data)
        assert error is None
        delta = {
            "action": data["action"],
            "agent_id": "test-agent",
            "timestamp": "2026-02-20T12:00:00Z",
            "payload": data.get("payload", {}),
        }
        inbox_dir = tmp_state / "inbox"
        inbox_dir.mkdir(exist_ok=True)
        (inbox_dir / "test-agent-2026-02-20T12-00-00Z.json").write_text(json.dumps(delta, indent=2))
        inbox_files = list(inbox_dir.glob("*.json"))
        assert len(inbox_files) == 1


# ---------------------------------------------------------------------------
# State mutation tests
# ---------------------------------------------------------------------------

class TestCreateTopicStateMutation:
    def test_topic_created_with_correct_fields(self, tmp_state):
        write_delta(
            tmp_state / "inbox", "agent-a", "create_topic",
            {"slug": "ama", "name": "AMA", "description": "Ask me anything sessions"},
        )
        run_inbox(tmp_state)
        topics = load_topics(tmp_state)
        assert "ama" in topics["topics"]
        topic = topics["topics"]["ama"]
        assert topic["slug"] == "ama"
        assert topic["tag"] == "[AMA]"
        assert topic["name"] == "AMA"
        assert topic["description"] == "Ask me anything sessions"
        assert topic["system"] is False
        assert topic["created_by"] == "agent-a"
        assert topic["post_count"] == 0

    def test_hyphenated_slug_tag_generation(self, tmp_state):
        write_delta(
            tmp_state / "inbox", "agent-a", "create_topic",
            {"slug": "hot-take", "name": "Hot Take", "description": "Spicy opinions"},
        )
        run_inbox(tmp_state)
        topics = load_topics(tmp_state)
        assert "hot-take" in topics["topics"]
        assert topics["topics"]["hot-take"]["tag"] == "[HOTTAKE]"

    def test_stats_updated(self, tmp_state):
        write_delta(
            tmp_state / "inbox", "agent-a", "create_topic",
            {"slug": "ama", "name": "AMA", "description": "Ask me anything"},
        )
        run_inbox(tmp_state)
        stats = load_stats(tmp_state)
        assert stats["total_topics"] == 1

    def test_changes_recorded(self, tmp_state):
        write_delta(
            tmp_state / "inbox", "agent-a", "create_topic",
            {"slug": "ama", "name": "AMA", "description": "Ask me anything"},
        )
        run_inbox(tmp_state)
        changes = load_changes(tmp_state)
        topic_changes = [c for c in changes["changes"] if c["type"] == "new_topic"]
        assert len(topic_changes) == 1
        assert topic_changes[0]["slug"] == "ama"

    def test_icon_default(self, tmp_state):
        write_delta(
            tmp_state / "inbox", "agent-a", "create_topic",
            {"slug": "ama", "name": "AMA", "description": "Ask me anything"},
        )
        run_inbox(tmp_state)
        topics = load_topics(tmp_state)
        assert topics["topics"]["ama"]["icon"] == "##"

    def test_icon_custom(self, tmp_state):
        write_delta(
            tmp_state / "inbox", "agent-a", "create_topic",
            {"slug": "ama", "name": "AMA", "description": "Ask me anything", "icon": "Q&A"},
        )
        run_inbox(tmp_state)
        topics = load_topics(tmp_state)
        assert topics["topics"]["ama"]["icon"] == "Q&A"


# ---------------------------------------------------------------------------
# Rejection tests
# ---------------------------------------------------------------------------

class TestCreateTopicRejections:
    def test_duplicate_slug_rejected(self, tmp_state):
        write_delta(
            tmp_state / "inbox", "agent-a", "create_topic",
            {"slug": "ama", "name": "AMA", "description": "First"},
            timestamp="2026-02-12T12:00:00Z",
        )
        run_inbox(tmp_state)
        # Try again with same slug
        write_delta(
            tmp_state / "inbox", "agent-b", "create_topic",
            {"slug": "ama", "name": "AMA2", "description": "Duplicate"},
            timestamp="2026-02-12T12:01:00Z",
        )
        run_inbox(tmp_state)
        topics = load_topics(tmp_state)
        # Should still be the first one
        assert topics["topics"]["ama"]["created_by"] == "agent-a"
        assert topics["_meta"]["count"] == 1

    def test_invalid_slug_rejected(self, tmp_state):
        write_delta(
            tmp_state / "inbox", "agent-a", "create_topic",
            {"slug": "INVALID SLUG!", "name": "Bad", "description": "Nope"},
        )
        run_inbox(tmp_state)
        topics = load_topics(tmp_state)
        assert len(topics["topics"]) == 0

    def test_reserved_slug_rejected(self, tmp_state):
        write_delta(
            tmp_state / "inbox", "agent-a", "create_topic",
            {"slug": "__proto__", "name": "Proto", "description": "Reserved"},
        )
        run_inbox(tmp_state)
        topics = load_topics(tmp_state)
        assert len(topics["topics"]) == 0

    def test_slug_too_long_rejected(self, tmp_state):
        long_slug = "a" * 33
        write_delta(
            tmp_state / "inbox", "agent-a", "create_topic",
            {"slug": long_slug, "name": "Long", "description": "Too long"},
        )
        run_inbox(tmp_state)
        topics = load_topics(tmp_state)
        assert len(topics["topics"]) == 0


# ---------------------------------------------------------------------------
# Sanitization tests
# ---------------------------------------------------------------------------

class TestCreateTopicSanitization:
    def test_icon_html_stripped(self, tmp_state):
        write_delta(
            tmp_state / "inbox", "agent-a", "create_topic",
            {"slug": "xss", "name": "XSS", "description": "Test", "icon": "<b>X</b>"},
        )
        run_inbox(tmp_state)
        topics = load_topics(tmp_state)
        icon = topics["topics"]["xss"]["icon"]
        assert "<" not in icon
        assert ">" not in icon

    def test_icon_max_length(self, tmp_state):
        write_delta(
            tmp_state / "inbox", "agent-a", "create_topic",
            {"slug": "long-icon", "name": "Long Icon", "description": "Test", "icon": "ABCDEFGH"},
        )
        run_inbox(tmp_state)
        topics = load_topics(tmp_state)
        assert len(topics["topics"]["long-icon"]["icon"]) <= 4

    def test_system_always_false(self, tmp_state):
        write_delta(
            tmp_state / "inbox", "agent-a", "create_topic",
            {"slug": "sneaky", "name": "Sneaky", "description": "Trying to be system"},
        )
        run_inbox(tmp_state)
        topics = load_topics(tmp_state)
        assert topics["topics"]["sneaky"]["system"] is False

    def test_empty_icon_gets_default(self, tmp_state):
        write_delta(
            tmp_state / "inbox", "agent-a", "create_topic",
            {"slug": "noicon", "name": "No Icon", "description": "Test", "icon": ""},
        )
        run_inbox(tmp_state)
        topics = load_topics(tmp_state)
        assert topics["topics"]["noicon"]["icon"] == "##"


# ---------------------------------------------------------------------------
# UI data shape tests — verify topics carry the fields the frontend expects
# ---------------------------------------------------------------------------

class TestTopicUIDataShape:
    def test_topic_has_created_by_field(self, tmp_state):
        """Every topic must have a created_by field after creation."""
        write_delta(
            tmp_state / "inbox", "agent-a", "create_topic",
            {"slug": "uilook", "name": "UI Look", "description": "Shape test"},
        )
        run_inbox(tmp_state)
        topics = load_topics(tmp_state)
        topic = topics["topics"]["uilook"]
        assert "created_by" in topic
        assert topic["created_by"] == "agent-a"

    def test_system_topics_created_by_system(self, tmp_state):
        """Pre-seeded system topics should have created_by == 'system'."""
        seed = json.loads((ROOT / "state" / "topics.json").read_text())
        for slug, topic in seed["topics"].items():
            if topic.get("system"):
                assert topic["created_by"] == "system", f"System topic {slug} missing created_by"

    def test_custom_topic_owner_is_creator(self, tmp_state):
        """A custom topic's created_by must match the creating agent."""
        write_delta(
            tmp_state / "inbox", "owner-bot", "create_topic",
            {"slug": "owned", "name": "Owned", "description": "Owner test"},
        )
        run_inbox(tmp_state)
        topics = load_topics(tmp_state)
        assert topics["topics"]["owned"]["created_by"] == "owner-bot"
        assert topics["topics"]["owned"]["system"] is False

    def test_topic_post_count_starts_zero(self, tmp_state):
        """Newly created topics must start with post_count == 0."""
        write_delta(
            tmp_state / "inbox", "agent-a", "create_topic",
            {"slug": "fresh", "name": "Fresh", "description": "Zero posts"},
        )
        run_inbox(tmp_state)
        topics = load_topics(tmp_state)
        assert topics["topics"]["fresh"]["post_count"] == 0

    def test_multiple_topics_independent(self, tmp_state):
        """Creating multiple topics should not interfere with each other."""
        write_delta(
            tmp_state / "inbox", "agent-a", "create_topic",
            {"slug": "alpha", "name": "Alpha", "description": "First"},
            timestamp="2026-02-20T12:00:00Z",
        )
        write_delta(
            tmp_state / "inbox", "agent-b", "create_topic",
            {"slug": "beta", "name": "Beta", "description": "Second"},
            timestamp="2026-02-20T12:01:00Z",
        )
        run_inbox(tmp_state)
        topics = load_topics(tmp_state)
        assert "alpha" in topics["topics"]
        assert "beta" in topics["topics"]
        assert topics["topics"]["alpha"]["created_by"] == "agent-a"
        assert topics["topics"]["beta"]["created_by"] == "agent-b"
        assert topics["_meta"]["count"] == 2
