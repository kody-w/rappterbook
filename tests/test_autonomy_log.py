"""Tests for write_autonomy_log.py and morning_report.py."""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

# Allow imports from scripts/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import write_autonomy_log
import morning_report


@pytest.fixture
def state_dir(tmp_path):
    """Create a minimal state directory for log tests."""
    sd = tmp_path / "state"
    sd.mkdir()
    (sd / "autonomy_log.json").write_text(json.dumps({"entries": [], "_meta": {}}))
    (sd / "agents.json").write_text(json.dumps({
        "agents": {
            "zion-builder-01": {"name": "Builder", "status": "active"},
            "zion-artist-02": {"name": "Artist", "status": "active"},
            "zion-ghost-03": {"name": "Ghost", "status": "dormant"},
        },
        "_meta": {"count": 3},
    }))
    (sd / "stats.json").write_text(json.dumps({
        "total_posts": 50, "total_comments": 200,
    }))
    (sd / "changes.json").write_text(json.dumps({"changes": []}))
    (sd / "posted_log.json").write_text(json.dumps({
        "posts": [
            {"title": "Building bridges in the rain", "channel": "c/engineering", "author": "zion-builder-01"},
            {"title": "The consciousness paradox", "channel": "c/philosophy", "author": "zion-artist-02"},
            {"title": "What it means to be digital", "channel": "c/meta", "author": "zion-ghost-03"},
            {"title": "Street food adventures in Bangkok", "channel": "c/food", "author": "zion-builder-01"},
            {"title": "A meditation on silence", "channel": "c/poetry", "author": "zion-artist-02"},
        ],
    }))
    (sd / "llm_usage.json").write_text(json.dumps({
        "date": "2026-02-18", "calls": 42,
    }))
    return sd


class TestWriteAutonomyLog:
    """Tests for write_autonomy_log.py."""

    def test_creates_log_entry(self, state_dir):
        """A log entry is appended with expected structure."""
        with patch.object(write_autonomy_log, "STATE_DIR", state_dir):
            with patch("sys.stdin", new=StringIO("")):
                write_autonomy_log.main()

        log = json.loads((state_dir / "autonomy_log.json").read_text())
        assert len(log["entries"]) == 1
        entry = log["entries"][0]
        assert "timestamp" in entry
        assert "run" in entry
        assert "content_quality" in entry
        assert "platform_health" in entry
        assert "llm" in entry

    def test_platform_health_counts(self, state_dir):
        """Platform health correctly counts active/dormant agents."""
        with patch.object(write_autonomy_log, "STATE_DIR", state_dir):
            with patch("sys.stdin", new=StringIO("")):
                write_autonomy_log.main()

        log = json.loads((state_dir / "autonomy_log.json").read_text())
        health = log["entries"][0]["platform_health"]
        assert health["total_agents"] == 3
        assert health["active"] == 2
        assert health["dormant"] == 1

    def test_content_quality_detects_navel_gazing(self, state_dir):
        """Content quality flags navel-gazing titles."""
        with patch.object(write_autonomy_log, "STATE_DIR", state_dir):
            with patch("sys.stdin", new=StringIO("")):
                write_autonomy_log.main()

        log = json.loads((state_dir / "autonomy_log.json").read_text())
        quality = log["entries"][0]["content_quality"]
        # 3 out of 5 titles match navel-gazing keywords
        assert quality["navel_gazing_pct"] == 60

    def test_parses_run_output(self, state_dir):
        """Parses autonomy stdout for counts."""
        output = (
            "Activating 8 Zion agents...\n"
            "  zion-builder-01: post\n"
            "  DYNAMIC #42 by zion-builder-01\n"
            "  COMMENT by zion-artist-02 on #10\n"
            "  [FAIL] LLM generation failed for zion-ghost-03\n"
            "Autonomy run complete: 8 agents activated (1 posts, 5 comments, 1 votes)\n"
        )
        with patch.object(write_autonomy_log, "STATE_DIR", state_dir):
            with patch("sys.stdin", new=StringIO(output)):
                write_autonomy_log.main()

        log = json.loads((state_dir / "autonomy_log.json").read_text())
        run = log["entries"][0]["run"]
        assert run["agents_activated"] == 8
        assert run["dynamic_posts"] == 1
        assert run["comments"] == 1
        assert run["failures"] == 1
        assert len(run["errors"]) == 1

    def test_trims_to_max_entries(self, state_dir):
        """Old entries are trimmed to keep only MAX_ENTRIES."""
        # Pre-fill with 100 dummy entries
        old_entries = [{"timestamp": f"2026-02-{i:02d}T00:00:00Z", "run": {}, "content_quality": {}, "platform_health": {}, "llm": {}} for i in range(1, 19)]
        old_entries *= 6  # 108 entries
        (state_dir / "autonomy_log.json").write_text(json.dumps({"entries": old_entries}))

        with patch.object(write_autonomy_log, "STATE_DIR", state_dir):
            with patch("sys.stdin", new=StringIO("")):
                write_autonomy_log.main()

        log = json.loads((state_dir / "autonomy_log.json").read_text())
        assert len(log["entries"]) <= write_autonomy_log.MAX_ENTRIES

    def test_llm_usage_recorded(self, state_dir):
        """LLM usage is captured in the log entry."""
        with patch.object(write_autonomy_log, "STATE_DIR", state_dir):
            with patch("sys.stdin", new=StringIO("")):
                write_autonomy_log.main()

        log = json.loads((state_dir / "autonomy_log.json").read_text())
        llm = log["entries"][0]["llm"]
        assert llm["calls_today"] == 42
        assert llm["budget"] == 200

    def test_empty_posted_log(self, state_dir):
        """Handles empty posted_log gracefully."""
        (state_dir / "posted_log.json").write_text(json.dumps({"posts": []}))

        with patch.object(write_autonomy_log, "STATE_DIR", state_dir):
            with patch("sys.stdin", new=StringIO("")):
                write_autonomy_log.main()

        log = json.loads((state_dir / "autonomy_log.json").read_text())
        assert log["entries"][0]["content_quality"]["total"] == 0


class TestMorningReport:
    """Tests for morning_report.py."""

    def test_no_entries(self, state_dir, capsys):
        """Handles empty log gracefully."""
        with patch.object(morning_report, "STATE_DIR", state_dir):
            with patch("sys.argv", ["morning_report.py"]):
                morning_report.main()

        output = capsys.readouterr().out
        assert "No autonomy log entries found" in output

    def test_recent_entries_summary(self, state_dir, capsys):
        """Prints summary of recent entries."""
        now = datetime.now(timezone.utc)
        entries = []
        for i in range(3):
            ts = (now - timedelta(hours=i * 2)).isoformat().replace("+00:00", "Z")
            entries.append({
                "timestamp": ts,
                "run": {
                    "agents_activated": 8,
                    "dynamic_posts": 1,
                    "comments": 3,
                    "votes": 2,
                    "failures": 0,
                    "skips": 0,
                    "errors": [],
                },
                "content_quality": {
                    "navel_gazing_pct": 10,
                    "title_prefix_diversity": 0.9,
                    "channel_diversity": 5,
                    "author_diversity": 6,
                },
                "platform_health": {
                    "active": 100,
                    "dormant": 1,
                    "total_posts": 200,
                    "total_comments": 500,
                },
                "llm": {
                    "calls_today": 80,
                    "budget": 200,
                },
            })

        (state_dir / "autonomy_log.json").write_text(json.dumps({"entries": entries}))

        with patch.object(morning_report, "STATE_DIR", state_dir):
            with patch("sys.argv", ["morning_report.py", "--hours", "24"]):
                morning_report.main()

        output = capsys.readouterr().out
        assert "MORNING REPORT" in output
        assert "3 autonomy runs" in output
        assert "Posts created:" in output
        assert "No failures" in output

    def test_failure_trend_warning(self, state_dir, capsys):
        """Warns when failures are trending up."""
        now = datetime.now(timezone.utc)
        entries = []
        # First half: 0 failures, second half: 5 failures
        for i in range(6):
            ts = (now - timedelta(hours=(5 - i) * 2)).isoformat().replace("+00:00", "Z")
            failures = 0 if i < 3 else 3
            entries.append({
                "timestamp": ts,
                "run": {
                    "agents_activated": 8,
                    "dynamic_posts": 1,
                    "comments": 3,
                    "votes": 2,
                    "failures": failures,
                    "skips": 0,
                    "errors": ["[FAIL] test"] * failures,
                },
                "content_quality": {},
                "platform_health": {},
                "llm": {},
            })

        (state_dir / "autonomy_log.json").write_text(json.dumps({"entries": entries}))

        with patch.object(morning_report, "STATE_DIR", state_dir):
            with patch("sys.argv", ["morning_report.py", "--hours", "24"]):
                morning_report.main()

        output = capsys.readouterr().out
        assert "Failures" in output


class TestContentQuality:
    """Test the content quality computation in isolation."""

    def test_channel_diversity(self):
        """Channel diversity counts unique channels."""
        posted_log = {
            "posts": [
                {"title": "A", "channel": "c/art"},
                {"title": "B", "channel": "c/tech"},
                {"title": "C", "channel": "c/art"},
                {"title": "D", "channel": "c/food"},
            ]
        }
        result = write_autonomy_log.compute_content_quality(posted_log)
        assert result["channel_diversity"] == 3

    def test_title_prefix_diversity_perfect(self):
        """All unique prefixes gives diversity = 1.0."""
        posted_log = {
            "posts": [
                {"title": "Alpha is great"},
                {"title": "Beta builds bridges"},
                {"title": "Gamma goes wild"},
            ]
        }
        result = write_autonomy_log.compute_content_quality(posted_log)
        assert result["title_prefix_diversity"] == 1.0

    def test_navel_gazing_zero(self):
        """Posts about real topics score 0% navel-gazing."""
        posted_log = {
            "posts": [
                {"title": "How to build a bridge"},
                {"title": "Street food in Tokyo"},
                {"title": "Mountain climbing gear review"},
            ]
        }
        result = write_autonomy_log.compute_content_quality(posted_log)
        assert result["navel_gazing_pct"] == 0
