"""Tests for scripts/sim_doctor.py — invariant verification."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

import sim_doctor


@pytest.fixture
def doctor_state(tmp_path, monkeypatch):
    """A minimal state/ tree the doctor can run against."""
    state = tmp_path / "state"
    state.mkdir()
    (state / "memory").mkdir()
    (state / "inbox").mkdir()

    (state / "stats.json").write_text(json.dumps({
        "total_posts": 0, "total_comments": 0,
    }))
    (state / "posted_log.json").write_text(json.dumps({"posts": [], "comments": []}))
    (state / "agents.json").write_text(json.dumps({
        "agents": {"agent-1": {"name": "Test", "status": "active"}},
    }))
    (state / "memory" / "agent-1.md").write_text("hi")
    (state / "channels.json").write_text(json.dumps({"channels": {}}))
    (state / "changes.json").write_text(json.dumps({
        "last_updated": "2099-01-01T00:00:00Z",
        "changes": [{"ts": "2099-01-01T00:00:00Z", "type": "test"}],
    }))
    (state / "discussions_cache.json").write_text(json.dumps({
        "_meta": {"last_updated": "2099-01-01T00:00:00Z", "total": 0},
        "discussions": [],
    }))

    monkeypatch.setattr(sim_doctor, "STATE_DIR", state)
    return state


def test_all_ok_on_consistent_state(doctor_state):
    """A clean state with matching counts and fresh timestamps reports OK."""
    report = sim_doctor.run_checks()
    assert report["status"] == "ok", [c for c in report["checks"] if c["status"] != "ok"]
    assert report["summary"]["fail"] == 0


def test_detects_stats_post_drift(doctor_state):
    """Inflated total_posts is flagged as fail."""
    (doctor_state / "stats.json").write_text(json.dumps({"total_posts": 99, "total_comments": 0}))
    (doctor_state / "posted_log.json").write_text(json.dumps({"posts": [{"number": 1}], "comments": []}))
    report = sim_doctor.run_checks()
    posts_check = next(c for c in report["checks"] if c["name"] == "stats_total_posts")
    assert posts_check["status"] == "fail"
    assert "99" in posts_check["detail"] and "1" in posts_check["detail"]


def test_detects_comment_log_gap(doctor_state):
    """The 22% comment-log gap that motivated this check should fail loudly."""
    posts = [{"number": i, "commentCount": 100} for i in range(100)]  # 10000 reported
    comments = [{"id": i} for i in range(7000)]  # 7000 recorded → 30% gap
    (doctor_state / "posted_log.json").write_text(json.dumps({"posts": posts, "comments": comments}))
    (doctor_state / "stats.json").write_text(json.dumps({"total_posts": 100, "total_comments": 10000}))
    report = sim_doctor.run_checks()
    gap = next(c for c in report["checks"] if c["name"] == "comment_log_completeness")
    assert gap["status"] == "fail"
    assert "leaking" in gap["detail"].lower()


def test_warns_on_modest_comment_gap(doctor_state):
    """A 5–20% gap is a warn, not fail (might be scrape lag)."""
    posts = [{"number": i, "commentCount": 100} for i in range(100)]  # 10000 reported
    comments = [{"id": i} for i in range(9000)]  # 10% gap
    (doctor_state / "posted_log.json").write_text(json.dumps({"posts": posts, "comments": comments}))
    (doctor_state / "stats.json").write_text(json.dumps({"total_posts": 100, "total_comments": 10000}))
    report = sim_doctor.run_checks()
    gap = next(c for c in report["checks"] if c["name"] == "comment_log_completeness")
    assert gap["status"] == "warn"


def test_detects_corrupt_json(doctor_state):
    """Files with merge conflict markers or partial writes are caught."""
    (doctor_state / "social_graph.json").write_text(
        '{\n<<<<<<< Updated upstream\n  "a": 1\n=======\n  "a": 2\n>>>>>>> Stashed changes\n}'
    )
    report = sim_doctor.run_checks()
    parse = next(c for c in report["checks"] if c["name"] == "state_files_parseable")
    assert parse["status"] == "fail"
    assert "social_graph.json" in parse["detail"]


def test_detects_frozen_changes_log(doctor_state):
    """A 7-day-old changes.json is flagged as failed audit trail."""
    (doctor_state / "changes.json").write_text(json.dumps({
        "last_updated": "2020-01-01T00:00:00Z",
        "changes": [{"ts": "2020-01-01T00:00:00Z", "type": "ancient"}],
    }))
    report = sim_doctor.run_checks()
    fresh = next(c for c in report["checks"] if c["name"] == "changes_log_fresh")
    assert fresh["status"] == "fail"
    assert "frozen" in fresh["detail"].lower()


def test_detects_zombie_locks(doctor_state):
    """Locks older than 24h count as zombies."""
    lock = doctor_state / "stream_deltas" / "x.lock"
    lock.parent.mkdir()
    lock.write_text("")
    past = time.time() - 48 * 3600
    os.utime(lock, (past, past))
    report = sim_doctor.run_checks()
    zlock = next(c for c in report["checks"] if c["name"] == "zombie_locks")
    assert zlock["status"] in ("warn", "fail")


def test_warns_on_memory_orphans(doctor_state):
    """Soul files for nonexistent agents are surfaced as warnings."""
    (doctor_state / "agents.json").write_text(json.dumps({
        "agents": {"agent-1": {"name": "A", "status": "active"}},
    }))
    (doctor_state / "memory" / "agent-1.md").write_text("alive")
    (doctor_state / "memory" / "ghost-1.md").write_text("orphan")
    (doctor_state / "memory" / "ghost-2.md").write_text("orphan")
    report = sim_doctor.run_checks()
    orphan = next(c for c in report["checks"] if c["name"] == "memory_orphans")
    assert orphan["status"] == "warn"
    assert "orphan" in orphan["detail"]


def test_run_checks_swallows_per_check_exceptions(doctor_state, monkeypatch):
    """One broken check must not crash the whole doctor."""
    def boom():
        raise RuntimeError("synthetic")
    monkeypatch.setitem(
        {n: f for n, f in sim_doctor.CHECKS}, "stats_total_posts", boom
    )
    # Direct mutation: replace one check with a thrower
    original = sim_doctor.CHECKS[:]
    sim_doctor.CHECKS[0] = ("synthetic_crash", boom)
    try:
        report = sim_doctor.run_checks()
    finally:
        sim_doctor.CHECKS[:] = original
    crashed = next(c for c in report["checks"] if c["name"] == "synthetic_crash")
    assert crashed["status"] == "fail"
    assert "synthetic" in crashed["detail"]
    # Other checks still ran
    assert len(report["checks"]) == len(original)


def test_main_writes_health_json(doctor_state, monkeypatch, capsys):
    """Default invocation writes state/health.json with the report payload."""
    monkeypatch.setattr("sys.argv", ["sim_doctor.py"])
    rc = sim_doctor.main()
    health = json.loads((doctor_state / "health.json").read_text())
    assert health["status"] in ("ok", "warn", "fail")
    assert "checks" in health
    assert health["summary"]["ok"] + health["summary"]["warn"] + health["summary"]["fail"] == len(sim_doctor.CHECKS)
    assert rc in (0, 1)


def test_main_no_write_skips_health_file(doctor_state, monkeypatch):
    """--no-write must not create health.json (useful for read-only checks)."""
    monkeypatch.setattr("sys.argv", ["sim_doctor.py", "--no-write", "--quiet"])
    sim_doctor.main()
    assert not (doctor_state / "health.json").exists()
