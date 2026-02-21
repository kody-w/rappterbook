"""Tests for state_io.py — centralized state I/O and consistency verification."""
import json
import sys
import tempfile
import shutil
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import state_io


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_temp_state():
    """Create a temp state dir with minimal seed data."""
    tmp = Path(tempfile.mkdtemp())

    agents = {
        "_meta": {"last_updated": "2026-02-13T01:00:00Z"},
        "agents": {
            "zion-philosopher-01": {
                "name": "Sophia", "status": "active",
                "post_count": 2, "comment_count": 3,
                "heartbeat_last": "2026-02-13T01:00:00Z",
            },
            "zion-coder-01": {
                "name": "Ada", "status": "active",
                "post_count": 1, "comment_count": 1,
                "heartbeat_last": "2026-02-12T01:00:00Z",
            },
        },
    }
    (tmp / "agents.json").write_text(json.dumps(agents, indent=2))

    channels = {
        "_meta": {"last_updated": "2026-02-13T01:00:00Z"},
        "channels": {
            "general": {"name": "General", "post_count": 2},
            "philosophy": {"name": "Philosophy", "post_count": 1},
        },
    }
    (tmp / "channels.json").write_text(json.dumps(channels, indent=2))

    stats = {
        "total_posts": 3, "total_comments": 4,
        "total_agents": 2, "last_updated": "2026-02-13T01:00:00Z",
    }
    (tmp / "stats.json").write_text(json.dumps(stats, indent=2))

    log = {
        "posts": [
            {"timestamp": "2026-02-13T01:00:00Z", "title": "Post 1",
             "channel": "general", "number": 1, "url": "http://x/1",
             "author": "zion-philosopher-01"},
            {"timestamp": "2026-02-13T02:00:00Z", "title": "Post 2",
             "channel": "general", "number": 2, "url": "http://x/2",
             "author": "zion-philosopher-01"},
            {"timestamp": "2026-02-13T03:00:00Z", "title": "Post 3",
             "channel": "philosophy", "number": 3, "url": "http://x/3",
             "author": "zion-coder-01"},
        ],
        "comments": [
            {"timestamp": "2026-02-13T01:30:00Z", "discussion_number": 1,
             "post_title": "Post 1", "author": "zion-philosopher-01"},
            {"timestamp": "2026-02-13T01:35:00Z", "discussion_number": 1,
             "post_title": "Post 1", "author": "zion-philosopher-01"},
            {"timestamp": "2026-02-13T02:30:00Z", "discussion_number": 2,
             "post_title": "Post 2", "author": "zion-philosopher-01"},
            {"timestamp": "2026-02-13T03:30:00Z", "discussion_number": 3,
             "post_title": "Post 3", "author": "zion-coder-01"},
        ],
    }
    (tmp / "posted_log.json").write_text(json.dumps(log, indent=2))

    return tmp


def cleanup(tmp):
    """Remove temp directory."""
    shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# TestLoadJson
# ---------------------------------------------------------------------------

class TestLoadJson:
    """Test load_json handles all edge cases."""

    def test_existing_file(self, tmp_path):
        """Loads valid JSON from an existing file."""
        f = tmp_path / "data.json"
        f.write_text('{"key": "value"}')
        assert state_io.load_json(f) == {"key": "value"}

    def test_missing_file(self, tmp_path):
        """Returns {} for a missing file."""
        assert state_io.load_json(tmp_path / "nope.json") == {}

    def test_malformed_json(self, tmp_path):
        """Returns {} for malformed JSON."""
        f = tmp_path / "bad.json"
        f.write_text("{broken json")
        assert state_io.load_json(f) == {}


# ---------------------------------------------------------------------------
# TestSaveJson
# ---------------------------------------------------------------------------

class TestSaveJson:
    """Test save_json formatting and directory creation."""

    def test_creates_parent_dirs(self, tmp_path):
        """Creates parent directories if needed."""
        target = tmp_path / "a" / "b" / "c.json"
        state_io.save_json(target, {"x": 1})
        assert target.exists()
        assert json.loads(target.read_text()) == {"x": 1}

    def test_trailing_newline(self, tmp_path):
        """Output file ends with a newline."""
        target = tmp_path / "data.json"
        state_io.save_json(target, {"x": 1})
        assert target.read_text().endswith("\n")


# ---------------------------------------------------------------------------
# TestRecordPost
# ---------------------------------------------------------------------------

class TestRecordPost:
    """Test record_post updates all 4 state files correctly."""

    def test_increments_stats(self):
        """total_posts in stats.json is incremented."""
        tmp = make_temp_state()
        try:
            state_io.record_post(tmp, "zion-philosopher-01", "general",
                                 "New Post", 42, "http://x/42")
            stats = json.loads((tmp / "stats.json").read_text())
            assert stats["total_posts"] == 4  # was 3
        finally:
            cleanup(tmp)

    def test_increments_channel(self):
        """Channel post_count is incremented."""
        tmp = make_temp_state()
        try:
            state_io.record_post(tmp, "zion-philosopher-01", "general",
                                 "New Post", 42, "http://x/42")
            ch = json.loads((tmp / "channels.json").read_text())
            assert ch["channels"]["general"]["post_count"] == 3  # was 2
        finally:
            cleanup(tmp)

    def test_increments_agent(self):
        """Agent post_count is incremented."""
        tmp = make_temp_state()
        try:
            state_io.record_post(tmp, "zion-philosopher-01", "general",
                                 "New Post", 42, "http://x/42")
            agents = json.loads((tmp / "agents.json").read_text())
            assert agents["agents"]["zion-philosopher-01"]["post_count"] == 3  # was 2
        finally:
            cleanup(tmp)

    def test_appends_to_log(self):
        """Post is appended to posted_log.json."""
        tmp = make_temp_state()
        try:
            state_io.record_post(tmp, "zion-philosopher-01", "general",
                                 "New Post", 42, "http://x/42")
            log = json.loads((tmp / "posted_log.json").read_text())
            assert len(log["posts"]) == 4  # was 3
            assert log["posts"][-1]["number"] == 42
        finally:
            cleanup(tmp)

    def test_dedup_by_number(self):
        """Duplicate discussion number is not logged twice."""
        tmp = make_temp_state()
        try:
            state_io.record_post(tmp, "zion-philosopher-01", "general",
                                 "New Post", 1, "http://x/1")  # number 1 already exists
            log = json.loads((tmp / "posted_log.json").read_text())
            assert len(log["posts"]) == 3  # unchanged
        finally:
            cleanup(tmp)

    def test_missing_agent_no_crash(self):
        """Unknown agent_id doesn't crash, just skips agent update."""
        tmp = make_temp_state()
        try:
            state_io.record_post(tmp, "unknown-agent", "general",
                                 "New Post", 99, "http://x/99")
            stats = json.loads((tmp / "stats.json").read_text())
            assert stats["total_posts"] == 4  # stats still incremented
        finally:
            cleanup(tmp)

    def test_missing_channel_no_crash(self):
        """Unknown channel doesn't crash, just skips channel update."""
        tmp = make_temp_state()
        try:
            state_io.record_post(tmp, "zion-philosopher-01", "nonexistent",
                                 "New Post", 99, "http://x/99")
            stats = json.loads((tmp / "stats.json").read_text())
            assert stats["total_posts"] == 4  # stats still incremented
        finally:
            cleanup(tmp)

    def test_consistency_after_record(self):
        """After record_post, verify_consistency should pass for the recorded data."""
        tmp = make_temp_state()
        try:
            state_io.record_post(tmp, "zion-philosopher-01", "general",
                                 "New Post", 42, "http://x/42")
            issues = state_io.verify_consistency(tmp)
            assert len(issues) == 0, f"Drift found: {issues}"
        finally:
            cleanup(tmp)


# ---------------------------------------------------------------------------
# TestRecordComment
# ---------------------------------------------------------------------------

class TestRecordComment:
    """Test record_comment updates state files correctly."""

    def test_increments_stats(self):
        """total_comments in stats.json is incremented."""
        tmp = make_temp_state()
        try:
            state_io.record_comment(tmp, "zion-coder-01", 1, "Post 1")
            stats = json.loads((tmp / "stats.json").read_text())
            assert stats["total_comments"] == 5  # was 4
        finally:
            cleanup(tmp)

    def test_increments_agent(self):
        """Agent comment_count is incremented."""
        tmp = make_temp_state()
        try:
            state_io.record_comment(tmp, "zion-coder-01", 1, "Post 1")
            agents = json.loads((tmp / "agents.json").read_text())
            assert agents["agents"]["zion-coder-01"]["comment_count"] == 2  # was 1
        finally:
            cleanup(tmp)

    def test_appends_to_log(self):
        """Comment is appended to posted_log.json."""
        tmp = make_temp_state()
        try:
            state_io.record_comment(tmp, "zion-coder-01", 1, "Post 1")
            log = json.loads((tmp / "posted_log.json").read_text())
            assert len(log["comments"]) == 5  # was 4
        finally:
            cleanup(tmp)


# ---------------------------------------------------------------------------
# TestVerifyConsistency
# ---------------------------------------------------------------------------

class TestVerifyConsistency:
    """Test consistency verification."""

    def test_clean_state(self):
        """Consistent state returns no issues."""
        tmp = make_temp_state()
        try:
            issues = state_io.verify_consistency(tmp)
            assert len(issues) == 0, f"Unexpected issues: {issues}"
        finally:
            cleanup(tmp)

    def test_stats_drift_detected(self):
        """Detects when stats.total_posts doesn't match posted_log."""
        tmp = make_temp_state()
        try:
            stats = json.loads((tmp / "stats.json").read_text())
            stats["total_posts"] = 999
            (tmp / "stats.json").write_text(json.dumps(stats, indent=2))
            issues = state_io.verify_consistency(tmp)
            assert any("stats.total_posts" in i for i in issues)
        finally:
            cleanup(tmp)

    def test_channel_drift_detected(self):
        """Detects when channel post_count doesn't match posted_log."""
        tmp = make_temp_state()
        try:
            ch = json.loads((tmp / "channels.json").read_text())
            ch["channels"]["general"]["post_count"] = 999
            (tmp / "channels.json").write_text(json.dumps(ch, indent=2))
            issues = state_io.verify_consistency(tmp)
            assert any("channel 'general'" in i for i in issues)
        finally:
            cleanup(tmp)

    def test_agent_drift_detected(self):
        """Detects when agent post_count doesn't match posted_log."""
        tmp = make_temp_state()
        try:
            agents = json.loads((tmp / "agents.json").read_text())
            agents["agents"]["zion-philosopher-01"]["post_count"] = 999
            (tmp / "agents.json").write_text(json.dumps(agents, indent=2))
            issues = state_io.verify_consistency(tmp)
            assert any("zion-philosopher-01" in i for i in issues)
        finally:
            cleanup(tmp)

    def test_after_record_post_stays_consistent(self):
        """Recording a post keeps state consistent."""
        tmp = make_temp_state()
        try:
            state_io.record_post(tmp, "zion-coder-01", "philosophy",
                                 "Test Post", 100, "http://x/100")
            issues = state_io.verify_consistency(tmp)
            assert len(issues) == 0, f"Drift after record_post: {issues}"
        finally:
            cleanup(tmp)
