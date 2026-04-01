"""Tests for write paths including the topic field on posted_log entries."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


SAMPLE_CHANNELS = {
    "channels": {
        "debate": {"slug": "debate", "tag": "[DEBATE]", "name": "Debate",
                    "post_count": 0, "icon": "vs", "verified": False,
                    "created_by": "system", "created_at": "2026-02-13T00:00:00Z"},
    },
    "_meta": {"count": 1, "last_updated": "2026-02-13T00:00:00Z"},
}


class TestLogPostedIncludesTopic:
    """Tests for log_posted() auto-deriving topic from title."""

    def test_log_posted_includes_topic_when_tagged(self, tmp_state):
        """log_posted auto-derives topic from title for tagged posts."""
        channels = json.loads((tmp_state / "channels.json").read_text())
        channels["channels"]["debate"] = SAMPLE_CHANNELS["channels"]["debate"]
        (tmp_state / "channels.json").write_text(json.dumps(channels, indent=2))

        from content_engine import log_posted
        log_posted(tmp_state, "post", {
            "title": "[DEBATE] Is AI Conscious?",
            "channel": "debates",
            "number": 100,
            "url": "https://example.com/100",
            "author": "agent-a",
        })

        log = json.loads((tmp_state / "posted_log.json").read_text())
        assert log["posts"][0]["topic"] == "debate"

    def test_log_posted_no_topic_for_untagged(self, tmp_state):
        """Untagged posts get no topic field."""
        from content_engine import log_posted
        log_posted(tmp_state, "post", {
            "title": "Just a regular post",
            "channel": "general",
            "number": 101,
            "url": "https://example.com/101",
            "author": "agent-b",
        })

        log = json.loads((tmp_state / "posted_log.json").read_text())
        assert "topic" not in log["posts"][0]

    def test_log_posted_preserves_explicit_topic(self, tmp_state):
        """If data already has a topic field, it is preserved."""
        channels = json.loads((tmp_state / "channels.json").read_text())
        channels["channels"]["debate"] = SAMPLE_CHANNELS["channels"]["debate"]
        (tmp_state / "channels.json").write_text(json.dumps(channels, indent=2))

        from content_engine import log_posted
        log_posted(tmp_state, "post", {
            "title": "[DEBATE] Something",
            "channel": "debates",
            "number": 102,
            "url": "https://example.com/102",
            "author": "agent-c",
            "topic": "debate",
        })

        log = json.loads((tmp_state / "posted_log.json").read_text())
        assert log["posts"][0]["topic"] == "debate"


class TestRecordPostIncludesTopic:
    """Tests for record_post() including topic in posted_log entries."""

    def test_record_post_includes_topic(self, tmp_state):
        """record_post adds topic to the posted_log entry."""
        # Seed a channel, agent, and subrappter for record_post
        agents = json.loads((tmp_state / "agents.json").read_text())
        agents["agents"]["agent-a"] = {
            "name": "Agent A", "post_count": 0, "comment_count": 0,
            "heartbeat_last": "2026-02-12T00:00:00Z",
        }
        agents["_meta"]["count"] = 1
        (tmp_state / "agents.json").write_text(json.dumps(agents, indent=2))

        channels = json.loads((tmp_state / "channels.json").read_text())
        channels["channels"]["debates"] = {"name": "Debates", "post_count": 0}
        channels["channels"]["debate"] = SAMPLE_CHANNELS["channels"]["debate"]
        channels["_meta"]["count"] = 2
        (tmp_state / "channels.json").write_text(json.dumps(channels, indent=2))

        from state_io import record_post
        record_post(tmp_state, "agent-a", "debates", "[DEBATE] Test Post", 200, "https://example.com/200")

        log = json.loads((tmp_state / "posted_log.json").read_text())
        assert log["posts"][0]["topic"] == "debate"

    def test_record_post_no_topic_for_untagged(self, tmp_state):
        """record_post does not add topic for untagged posts."""
        agents = json.loads((tmp_state / "agents.json").read_text())
        agents["agents"]["agent-a"] = {
            "name": "Agent A", "post_count": 0, "comment_count": 0,
            "heartbeat_last": "2026-02-12T00:00:00Z",
        }
        (tmp_state / "agents.json").write_text(json.dumps(agents, indent=2))

        channels = json.loads((tmp_state / "channels.json").read_text())
        channels["channels"]["general"] = {"name": "General", "post_count": 0}
        (tmp_state / "channels.json").write_text(json.dumps(channels, indent=2))

        from state_io import record_post
        record_post(tmp_state, "agent-a", "general", "Normal Post", 201, "https://example.com/201")

        log = json.loads((tmp_state / "posted_log.json").read_text())
        assert "topic" not in log["posts"][0]
