"""Tests for compute_frame_echo.py — EREVSF frame echo system."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "compute_frame_echo.py"

sys.path.insert(0, str(ROOT / "scripts"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hours_ago(hours: float) -> str:
    dt = datetime.now(timezone.utc) - timedelta(hours=hours)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _seed_discussions(state_dir: Path, count: int = 20, channel: str = "general") -> None:
    """Write fake discussions_cache.json with `count` recent discussions."""
    discussions = []
    for i in range(count):
        discussions.append({
            "number": 10000 + i,
            "title": f"[DEBATE] Test discussion {i}",
            "category_slug": channel if i % 3 != 0 else "philosophy",
            "created_at": _hours_ago(i * 2),
            "comment_count": i % 5 + 1,
            "upvotes": i % 3,
            "author_login": "kody-w",
        })
    cache = {
        "_meta": {"total": count, "scraped_at": _now_iso()},
        "discussions": discussions,
    }
    (state_dir / "discussions_cache.json").write_text(json.dumps(cache, indent=2))


def _seed_autonomy_log(state_dir: Path, runs: int = 5) -> None:
    """Write fake autonomy_log.json."""
    entries = []
    for i in range(runs):
        entries.append({
            "timestamp": _hours_ago(i * 3),
            "run": {
                "posts": 3, "comments": 8, "votes": 5,
                "failures": 1, "agents_activated": 15,
            },
        })
    log = {"entries": entries, "_meta": {"total": runs}}
    (state_dir / "autonomy_log.json").write_text(json.dumps(log, indent=2))


def run_echo(state_dir: Path, extra_args: list | None = None) -> subprocess.CompletedProcess:
    """Run compute_frame_echo.py as a subprocess."""
    cmd = [sys.executable, str(SCRIPT)] + (extra_args or [])
    env = os.environ.copy()
    env["STATE_DIR"] = str(state_dir)
    return subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=str(ROOT))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBuildFrameEcho:
    """Test the echo builder."""

    def test_produces_valid_echo(self, tmp_state):
        """build_frame_echo returns a well-structured echo dict."""
        from compute_frame_echo import build_frame_echo

        _seed_discussions(tmp_state)
        _seed_autonomy_log(tmp_state)

        echo = build_frame_echo(tmp_state, frame_number=100)

        assert echo["frame"] == 100
        assert "echo_timestamp" in echo
        assert echo["source_platform"] == "rappterbook"
        assert "signals" in echo
        assert "discourse_shift" in echo["signals"]
        assert "engagement_pulse" in echo["signals"]
        assert "agent_activity" in echo["signals"]
        assert "trending_themes" in echo["signals"]
        assert "steering_hints" in echo
        assert "platform_snapshot" in echo

    def test_discourse_shift_detects_heating(self, tmp_state):
        """Discourse shift detects a channel heating up."""
        from compute_frame_echo import extract_discourse_shift

        # Create discussions: 10 recent in "code", 1 older in "code"
        discussions = []
        for i in range(10):
            discussions.append({
                "created_at": _hours_ago(2),
                "category_slug": "code",
            })
        discussions.append({
            "created_at": _hours_ago(30),
            "category_slug": "code",
        })

        result = extract_discourse_shift(discussions, hours=48.0)
        shifts = result["shifts"]
        assert any(s["channel"] == "code" and s["direction"] == "heating" for s in shifts)

    def test_discourse_shift_detects_cooling(self, tmp_state):
        """Discourse shift detects a channel cooling down."""
        from compute_frame_echo import extract_discourse_shift

        discussions = []
        # 1 recent, 10 older
        discussions.append({
            "created_at": _hours_ago(2),
            "category_slug": "debates",
        })
        for i in range(10):
            discussions.append({
                "created_at": _hours_ago(30),
                "category_slug": "debates",
            })

        result = extract_discourse_shift(discussions, hours=48.0)
        shifts = result["shifts"]
        assert any(s["channel"] == "debates" and s["direction"] == "cooling" for s in shifts)

    def test_engagement_pulse_metrics(self, tmp_state):
        """Engagement pulse computes correct averages."""
        from compute_frame_echo import extract_engagement_pulse

        discussions = [
            {"created_at": _hours_ago(1), "comment_count": 10, "upvotes": 5, "number": 1, "title": "A"},
            {"created_at": _hours_ago(2), "comment_count": 6, "upvotes": 3, "number": 2, "title": "B"},
        ]
        result = extract_engagement_pulse(discussions, hours=24.0)
        assert result["posts"] == 2
        assert result["avg_comments"] == 8.0
        assert result["avg_upvotes"] == 4.0
        assert result["most_discussed"]["number"] == 1

    def test_empty_state_doesnt_crash(self, tmp_state):
        """Echo builds cleanly from empty state."""
        from compute_frame_echo import build_frame_echo

        echo = build_frame_echo(tmp_state, frame_number=0)
        assert echo["frame"] == 0
        assert echo["signals"]["engagement_pulse"]["posts"] == 0


class TestCoherenceCheck:
    """Test the downstream coherence checker."""

    def test_duplicate_rejected_within_cooldown(self):
        """Duplicate frame+platform echo within 2h is rejected."""
        from compute_frame_echo import check_coherence

        existing = [{
            "frame": 100,
            "source_platform": "rappterbook",
            "echo_timestamp": _hours_ago(0.5),  # 30 min ago
        }]
        new_echo = {"frame": 100, "source_platform": "rappterbook"}
        violations = check_coherence(new_echo, existing)
        assert len(violations) == 1
        assert "cooldown" in violations[0]

    def test_duplicate_allowed_after_cooldown(self):
        """Same frame+platform echo allowed after 2h cooldown."""
        from compute_frame_echo import check_coherence

        existing = [{
            "frame": 100,
            "source_platform": "rappterbook",
            "echo_timestamp": _hours_ago(3),  # 3 hours ago
        }]
        new_echo = {"frame": 100, "source_platform": "rappterbook"}
        violations = check_coherence(new_echo, existing)
        assert len(violations) == 0

    def test_different_platform_always_allowed(self):
        """Different platform can echo the same frame immediately."""
        from compute_frame_echo import check_coherence

        existing = [{
            "frame": 100,
            "source_platform": "rappterbook",
            "echo_timestamp": _hours_ago(0.1),
        }]
        new_echo = {"frame": 100, "source_platform": "rappterverse"}
        violations = check_coherence(new_echo, existing)
        assert len(violations) == 0

    def test_negative_frame_rejected(self):
        """Negative frame numbers are rejected."""
        from compute_frame_echo import check_coherence

        violations = check_coherence({"frame": -1}, [])
        assert len(violations) == 1


class TestCLI:
    """Test the CLI subprocess invocation."""

    def test_dry_run(self, tmp_state):
        """--dry-run prints echo without writing."""
        _seed_discussions(tmp_state)
        _seed_autonomy_log(tmp_state)

        result = run_echo(tmp_state, ["--dry-run", "--frame", "42"])
        assert result.returncode == 0
        assert '"frame": 42' in result.stdout

        # Verify nothing was written
        echoes = json.loads((tmp_state / "frame_echoes.json").read_text())
        assert len(echoes["echoes"]) == 0

    def test_writes_echo(self, tmp_state):
        """Normal run appends echo to frame_echoes.json."""
        _seed_discussions(tmp_state)
        _seed_autonomy_log(tmp_state)

        result = run_echo(tmp_state, ["--frame", "469"])
        assert result.returncode == 0
        assert "Frame echo #469 stored" in result.stdout

        echoes = json.loads((tmp_state / "frame_echoes.json").read_text())
        assert len(echoes["echoes"]) == 1
        assert echoes["echoes"][0]["frame"] == 469
        assert echoes["_meta"]["total_echoes"] == 1

    def test_duplicate_blocked(self, tmp_state):
        """Running twice within 2h blocks the second echo."""
        _seed_discussions(tmp_state)
        _seed_autonomy_log(tmp_state)

        result1 = run_echo(tmp_state, ["--frame", "100"])
        assert result1.returncode == 0

        result2 = run_echo(tmp_state, ["--frame", "100"])
        assert result2.returncode == 1
        assert "cooldown" in result2.stdout

    def test_additive_only(self, tmp_state):
        """Multiple echoes for different frames all coexist."""
        _seed_discussions(tmp_state)
        _seed_autonomy_log(tmp_state)

        run_echo(tmp_state, ["--frame", "100"])
        run_echo(tmp_state, ["--frame", "101"])
        run_echo(tmp_state, ["--frame", "102"])

        echoes = json.loads((tmp_state / "frame_echoes.json").read_text())
        assert len(echoes["echoes"]) == 3
        frames = [e["frame"] for e in echoes["echoes"]]
        assert frames == [100, 101, 102]
