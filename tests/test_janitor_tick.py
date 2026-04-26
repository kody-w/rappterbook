"""Tests for scripts/janitor_tick.py — zombie lock sweeping."""
from __future__ import annotations

import fcntl
import os
import time
from pathlib import Path

import pytest

from janitor_tick import sweep_zombie_locks


def _make_lock(path: Path, age_hours: float) -> None:
    """Create a .lock file and back-date its mtime by age_hours."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("")
    past = time.time() - (age_hours * 3600)
    os.utime(path, (past, past))


def test_sweeps_locks_in_nested_subdirs(tmp_path: Path) -> None:
    """Janitor must sweep locks anywhere under state/, not just inbox/."""
    state = tmp_path / "state"
    _make_lock(state / "inbox" / "old.lock", age_hours=48)
    _make_lock(state / "stream_deltas" / "frame-515-x.json.lock", age_hours=48)
    _make_lock(state / "memory" / "agent-1.md.lock", age_hours=48)

    result = sweep_zombie_locks(state, max_age_hours=24, dry_run=False)

    assert result["found"] == 3
    assert result["removed"] == 3
    assert not (state / "inbox" / "old.lock").exists()
    assert not (state / "stream_deltas" / "frame-515-x.json.lock").exists()
    assert not (state / "memory" / "agent-1.md.lock").exists()


def test_respects_age_threshold(tmp_path: Path) -> None:
    """Locks newer than max_age_hours must be left alone (active writers)."""
    state = tmp_path / "state"
    _make_lock(state / "stream_deltas" / "fresh.lock", age_hours=0.5)
    _make_lock(state / "stream_deltas" / "stale.lock", age_hours=48)

    result = sweep_zombie_locks(state, max_age_hours=24, dry_run=False)

    assert result["found"] == 1
    assert result["removed"] == 1
    assert (state / "stream_deltas" / "fresh.lock").exists()
    assert not (state / "stream_deltas" / "stale.lock").exists()


def test_skips_live_locks_held_by_flock(tmp_path: Path) -> None:
    """Locks currently held via flock must be skipped, even when stale-aged.

    This is the race-safety gate: an old mtime alone is not proof of zombie
    status — a long-running writer could be mid-fsync. Only locks that no
    process holds get swept.
    """
    state = tmp_path / "state"
    held = state / "stream_deltas" / "held.lock"
    free = state / "stream_deltas" / "free.lock"
    _make_lock(held, age_hours=48)
    _make_lock(free, age_hours=48)

    # Hold an exclusive flock on `held` for the duration of the sweep.
    # Re-stamp mtime after open() since some platforms refresh it.
    fd = open(held, "a")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        past = time.time() - (48 * 3600)
        os.utime(held, (past, past))
        result = sweep_zombie_locks(state, max_age_hours=24, dry_run=False)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        fd.close()

    assert result["found"] == 2
    assert result["removed"] == 1
    assert result["skipped_live"] == 1
    assert held.exists(), "Live lock must not be deleted"
    assert not free.exists()


def test_dry_run_unlinks_nothing(tmp_path: Path) -> None:
    """Dry-run reports candidates without mutating disk."""
    state = tmp_path / "state"
    _make_lock(state / "stream_deltas" / "stale.lock", age_hours=48)

    result = sweep_zombie_locks(state, max_age_hours=24, dry_run=True)

    assert result["found"] == 1
    assert result["removed"] == 0
    assert (state / "stream_deltas" / "stale.lock").exists()


def test_missing_state_dir_is_noop(tmp_path: Path) -> None:
    """Janitor must tolerate a missing state directory."""
    result = sweep_zombie_locks(tmp_path / "nope", max_age_hours=24, dry_run=False)
    assert result == {"found": 0, "removed": 0, "skipped_live": 0, "files": []}
