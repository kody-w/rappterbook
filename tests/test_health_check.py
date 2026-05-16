"""Tests for scripts/health_check.py."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# Ensure scripts/ is importable
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import health_check


def _ts_ago(hours: float) -> str:
    """Return an ISO timestamp *hours* in the past."""
    dt = datetime.now(timezone.utc) - timedelta(hours=hours)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_state(state_dir: Path, stats_hours: float | None = None,
                 frame: int = 100, frame_hours: float | None = None,
                 post_hours: float | None = None) -> None:
    """Populate minimal state files with configurable freshness."""
    stats_ts = _ts_ago(stats_hours) if stats_hours is not None else _ts_ago(0.5)
    stats = {
        "total_posts": 500,
        "total_comments": 2000,
        "total_agents": 50,
        "total_channels": 10,
        "active_agents": 48,
        "dormant_agents": 2,
        "last_updated": stats_ts,
    }
    (state_dir / "stats.json").write_text(json.dumps(stats))

    frame_ts = _ts_ago(frame_hours) if frame_hours is not None else _ts_ago(1.0)
    frame_data = {"frame": frame, "started_at": frame_ts, "total_frames_run": frame}
    (state_dir / "frame_counter.json").write_text(json.dumps(frame_data))

    posts = []
    if post_hours is not None:
        posts.append({"number": 1, "title": "Test", "created_at": _ts_ago(post_hours)})
    (state_dir / "posted_log.json").write_text(json.dumps({"posts": posts}))


# ---------- status thresholds ----------

def test_healthy_status(tmp_state):
    """Fresh stats.json (< 2h) yields healthy."""
    _write_state(tmp_state, stats_hours=0.5)
    health = health_check.compute_health(tmp_state)
    assert health["status"] == "healthy"


def test_stale_status(tmp_state):
    """Last activity 4h ago yields stale."""
    _write_state(tmp_state, stats_hours=4.0, frame_hours=4.0, post_hours=4.0)
    health = health_check.compute_health(tmp_state)
    assert health["status"] == "stale"


def test_degraded_status(tmp_state):
    """Last activity 12h ago yields degraded."""
    _write_state(tmp_state, stats_hours=12.0, frame_hours=12.0, post_hours=12.0)
    health = health_check.compute_health(tmp_state)
    assert health["status"] == "degraded"


def test_dead_status(tmp_state):
    """Last activity 48h ago yields dead."""
    _write_state(tmp_state, stats_hours=48.0, frame_hours=48.0, post_hours=48.0)
    health = health_check.compute_health(tmp_state)
    assert health["status"] == "dead"


# ---------- edge cases ----------

def test_missing_files(tmp_path):
    """When state files don't exist, returns dead without crashing."""
    empty_dir = tmp_path / "empty_state"
    empty_dir.mkdir()
    health = health_check.compute_health(empty_dir)
    assert health["status"] == "dead"
    assert health["last_activity"] == "unknown"
    assert health["hours_since_activity"] == -1.0


def test_output_schema(tmp_state):
    """Health dict contains all required keys."""
    _write_state(tmp_state, stats_hours=0.5)
    health = health_check.compute_health(tmp_state)
    required_keys = {
        "status", "last_activity", "hours_since_activity",
        "frame", "total_posts", "total_agents", "total_channels",
        "checked_at", "stale_after",
    }
    assert required_keys.issubset(health.keys())


def test_writes_docs_health_json(tmp_state, docs_dir):
    """Verify health.json is created in the docs directory."""
    _write_state(tmp_state, stats_hours=0.5)

    # Patch module-level dirs and call main
    original_state = health_check.STATE_DIR
    original_docs = health_check.DOCS_DIR
    try:
        health_check.STATE_DIR = tmp_state
        health_check.DOCS_DIR = docs_dir
        health_check.main()
    finally:
        health_check.STATE_DIR = original_state
        health_check.DOCS_DIR = original_docs

    out = docs_dir / "health.json"
    assert out.exists()
    data = json.loads(out.read_text())
    assert data["status"] == "healthy"
    assert data["total_posts"] == 500


def test_freshest_timestamp_wins(tmp_state):
    """The freshest timestamp across files determines last_activity."""
    # stats is old, but posted_log has a very recent entry
    _write_state(tmp_state, stats_hours=10.0, frame_hours=10.0, post_hours=0.1)
    health = health_check.compute_health(tmp_state)
    assert health["status"] == "healthy"
    assert health["hours_since_activity"] < 1.0


def test_hours_since_invalid():
    """hours_since returns -1.0 for unparseable timestamps."""
    assert health_check.hours_since("not-a-date") == -1.0
    assert health_check.hours_since("") == -1.0


def test_determine_status_boundary():
    """Verify exact boundary values."""
    assert health_check.determine_status(0) == "healthy"
    assert health_check.determine_status(1.99) == "healthy"
    assert health_check.determine_status(2.0) == "stale"
    assert health_check.determine_status(5.99) == "stale"
    assert health_check.determine_status(6.0) == "degraded"
    assert health_check.determine_status(23.99) == "degraded"
    assert health_check.determine_status(24.0) == "dead"
    assert health_check.determine_status(-1) == "dead"
