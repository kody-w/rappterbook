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


def test_detects_conflict_markers_in_text_files(doctor_state):
    """Markdown soul files with conflict markers must be flagged.

    state_files_parseable would not catch this — only JSON gets parsed.
    The conflict-marker check covers any text file under state/.
    """
    soul = doctor_state / "memory" / "agent-1.md"
    soul.write_text(
        "ok line\n<<<<<<< Updated upstream\nlocal version\n=======\nremote version\n>>>>>>> Stashed changes\n"
    )
    report = sim_doctor.run_checks()
    cm = next(c for c in report["checks"] if c["name"] == "no_conflict_markers")
    assert cm["status"] == "fail"
    assert "memory/agent-1.md" in cm["detail"]


def test_no_conflict_markers_passes_on_clean(doctor_state):
    """Clean state with no markers reports OK."""
    report = sim_doctor.run_checks()
    cm = next(c for c in report["checks"] if c["name"] == "no_conflict_markers")
    assert cm["status"] == "ok"


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


# ---------------------------------------------------------------------------
# --fix mode + history append + --history view.
# ---------------------------------------------------------------------------

def test_main_appends_to_health_history(doctor_state, monkeypatch):
    """Every default doctor run appends one line to health_history.jsonl."""
    monkeypatch.setattr("sys.argv", ["sim_doctor.py", "--quiet"])
    sim_doctor.main()
    sim_doctor.main()
    history = (doctor_state / "health_history.jsonl").read_text().strip().split("\n")
    assert len(history) == 2
    for line in history:
        e = json.loads(line)
        assert "ts" in e and "status" in e and "ok" in e
        assert isinstance(e.get("fail_names"), list)


def test_no_write_skips_history_too(doctor_state, monkeypatch):
    """--no-write also skips the history append, not just health.json."""
    monkeypatch.setattr("sys.argv", ["sim_doctor.py", "--no-write", "--quiet"])
    sim_doctor.main()
    assert not (doctor_state / "health_history.jsonl").exists()


def test_fix_zombie_locks_actually_sweeps(doctor_state, monkeypatch):
    """fix_zombie_locks must invoke the janitor's race-safe sweeper."""
    lock = doctor_state / "stream_deltas" / "old.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text("")
    past = time.time() - 48 * 3600
    os.utime(lock, (past, past))
    fixed, detail = sim_doctor.fix_zombie_locks()
    assert fixed is True
    assert not lock.exists()
    assert "1" in detail


def test_fix_stats_drift_corrects_inflated_counter(doctor_state):
    """fix_stats_drift uses apply_posted_log_truth to lower inflated counters."""
    (doctor_state / "stats.json").write_text(json.dumps({"total_posts": 99, "total_comments": 999}))
    (doctor_state / "posted_log.json").write_text(json.dumps({
        "posts": [{"number": 1, "commentCount": 5}, {"number": 2, "commentCount": 3}],
    }))
    fixed, detail = sim_doctor.fix_stats_drift()
    assert fixed is True
    stats = json.loads((doctor_state / "stats.json").read_text())
    assert stats["total_posts"] == 2
    assert stats["total_comments"] == 8


def test_fix_stats_drift_noop_when_aligned(doctor_state):
    """No correction reported when stats already match posted_log truth."""
    (doctor_state / "stats.json").write_text(json.dumps({"total_posts": 1, "total_comments": 5}))
    (doctor_state / "posted_log.json").write_text(json.dumps({"posts": [{"number": 1, "commentCount": 5}]}))
    fixed, _ = sim_doctor.fix_stats_drift()
    assert fixed is False


def test_fix_memory_orphans_archives_not_deletes(doctor_state):
    """Orphan soul files are MOVED to state/archive/memory_orphans/{ts}/."""
    (doctor_state / "agents.json").write_text(json.dumps({
        "agents": {"agent-1": {"name": "A", "status": "active"}},
    }))
    (doctor_state / "memory" / "agent-1.md").write_text("alive")
    (doctor_state / "memory" / "ghost.md").write_text("orphan body")
    fixed, _ = sim_doctor.fix_memory_orphans()
    assert fixed is True
    assert not (doctor_state / "memory" / "ghost.md").exists()
    assert (doctor_state / "memory" / "agent-1.md").exists()
    archive_root = doctor_state / "archive" / "memory_orphans"
    assert archive_root.exists()
    archived = list(archive_root.rglob("ghost.md"))
    assert len(archived) == 1
    assert archived[0].read_text() == "orphan body"


def test_fix_memory_orphans_refuses_when_agents_empty(doctor_state):
    """Refuse to archive everything when agents.json is empty (would orphan all)."""
    (doctor_state / "agents.json").write_text(json.dumps({"agents": {}}))
    (doctor_state / "memory" / "ghost.md").write_text("orphan")
    fixed, detail = sim_doctor.fix_memory_orphans()
    assert fixed is False
    assert "empty" in detail.lower()
    assert (doctor_state / "memory" / "ghost.md").exists()


def test_show_history_renders_recent_runs(doctor_state, monkeypatch, capsys):
    """--history N reads health_history.jsonl and prints the last N runs."""
    history = doctor_state / "health_history.jsonl"
    history.write_text(
        json.dumps({"ts": "2026-04-26T00:00:00Z", "status": "ok",
                    "ok": 9, "warn": 0, "fail": 0, "fail_names": []}) + "\n" +
        json.dumps({"ts": "2026-04-26T01:00:00Z", "status": "fail",
                    "ok": 7, "warn": 0, "fail": 2,
                    "fail_names": ["zombie_locks", "stats_total_posts"]}) + "\n"
    )
    monkeypatch.setattr("sys.argv", ["sim_doctor.py", "--history", "5"])
    rc = sim_doctor.main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "2026-04-26T00:00:00Z" in out
    assert "2026-04-26T01:00:00Z" in out
    assert "zombie_locks" in out


def test_show_history_handles_missing_file(doctor_state, monkeypatch, capsys):
    """--history with no history file is a no-op, not a crash."""
    monkeypatch.setattr("sys.argv", ["sim_doctor.py", "--history", "5"])
    rc = sim_doctor.main()
    assert rc == 0
    assert "no history" in capsys.readouterr().out.lower()
