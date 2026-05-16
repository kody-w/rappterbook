"""Tests for the append-only event log (dual-write in state_io)."""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

# Ensure scripts/ is on the path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from state_io import append_event, record_post, record_comment


@pytest.fixture
def event_state(tmp_state):
    """State dir with event log support."""
    return tmp_state


class TestAppendEvent:
    """Tests for the append_event function."""

    def test_creates_jsonl_file(self, event_state):
        append_event("test.event", agent_id="agent-1", data={"foo": "bar"}, state_dir=event_state)
        log_path = event_state / "event_log.jsonl"
        assert log_path.is_file()

    def test_valid_jsonl(self, event_state):
        append_event("test.event", agent_id="agent-1", state_dir=event_state)
        append_event("test.event2", agent_id="agent-2", state_dir=event_state)
        log_path = event_state / "event_log.jsonl"
        lines = log_path.read_text().strip().split("\n")
        assert len(lines) == 2
        for line in lines:
            parsed = json.loads(line)
            assert "type" in parsed
            assert "timestamp" in parsed

    def test_event_schema(self, event_state):
        append_event("post.created", agent_id="zion-coder-01", frame=42,
                      data={"title": "Hello", "channel": "code"}, state_dir=event_state)
        log_path = event_state / "event_log.jsonl"
        event = json.loads(log_path.read_text().strip())
        assert event["type"] == "post.created"
        assert event["agent_id"] == "zion-coder-01"
        assert event["frame"] == 42
        assert event["data"]["title"] == "Hello"
        assert event["data"]["channel"] == "code"
        assert "timestamp" in event

    def test_append_is_additive(self, event_state):
        for i in range(10):
            append_event(f"test.{i}", agent_id=f"agent-{i}", state_dir=event_state)
        log_path = event_state / "event_log.jsonl"
        lines = log_path.read_text().strip().split("\n")
        assert len(lines) == 10

    def test_never_crashes(self, event_state):
        """Event logging must never raise, even with bad input."""
        append_event("", state_dir=event_state)  # empty type
        append_event("test", state_dir=Path("/nonexistent/path"))  # bad path
        # If we get here without exception, the test passes

    def test_concurrent_appends(self, event_state):
        """Multiple threads appending should not corrupt the file."""
        def append_n(n):
            for i in range(n):
                append_event(f"thread.{threading.current_thread().name}.{i}",
                             agent_id="concurrent", state_dir=event_state)

        threads = [threading.Thread(target=append_n, args=(20,)) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        log_path = event_state / "event_log.jsonl"
        lines = log_path.read_text().strip().split("\n")
        assert len(lines) == 100  # 5 threads x 20 events


class TestRecordPostDualWrite:
    """Tests that record_post also writes to event log."""

    def test_record_post_creates_event(self, event_state):
        record_post(event_state, title="Test Post", channel="general",
                    number=999, agent_id="agent-1", url="https://example.com/999")
        log_path = event_state / "event_log.jsonl"
        assert log_path.is_file()
        event = json.loads(log_path.read_text().strip())
        assert event["type"] == "post.created"
        assert event["agent_id"] == "agent-1"
        assert event["data"]["title"] == "Test Post"
        assert event["data"]["channel"] == "general"
        assert event["data"]["number"] == 999


class TestRecordCommentDualWrite:
    """Tests that record_comment also writes to event log."""

    def test_record_comment_creates_event(self, event_state):
        record_comment(event_state, agent_id="agent-2", number=42, title="Test")
        log_path = event_state / "event_log.jsonl"
        assert log_path.is_file()
        event = json.loads(log_path.read_text().strip())
        assert event["type"] == "comment.created"
        assert event["agent_id"] == "agent-2"
        assert event["data"]["number"] == 42


class TestRebuildFromLog:
    """Tests for rebuild_from_log.py."""

    def test_rebuild_counts(self, event_state):
        # Import here to avoid path issues
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
        from rebuild_from_log import read_event_log, rebuild_counts

        # Create some events
        append_event("post.created", agent_id="a1", state_dir=event_state)
        append_event("post.created", agent_id="a1", state_dir=event_state)
        append_event("post.created", agent_id="a2", state_dir=event_state)
        append_event("comment.created", agent_id="a1", state_dir=event_state)

        events = read_event_log(event_state)
        assert len(events) == 4

        counts = rebuild_counts(events)
        assert counts["total_posts"] == 3
        assert counts["total_comments"] == 1
        assert counts["agents"]["a1"]["posts"] == 2
        assert counts["agents"]["a1"]["comments"] == 1
        assert counts["agents"]["a2"]["posts"] == 1

    def test_empty_log(self, event_state):
        from rebuild_from_log import read_event_log, rebuild_counts
        events = read_event_log(event_state)
        assert events == []
        counts = rebuild_counts(events)
        assert counts["total_posts"] == 0
