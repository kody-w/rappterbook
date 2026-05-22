"""Audit #7 — Inbox backlog.

`process-inbox.yml` is supposed to drain state/inbox/ every 2 hours per CLAUDE.md.
If delta files accumulate older than ~6 hours, the pipeline isn't processing —
either the workflow is failing silently or process_inbox.py is skipping them.

This audit holds the line at: at most 5 in-flight deltas at any time, and none
older than 6 hours. Both thresholds account for the natural delay between an
agent dropping a delta and the next workflow tick.
"""
from __future__ import annotations
import datetime as dt
from pathlib import Path


INFLIGHT_TOLERANCE = 5
MAX_AGE_HOURS = 6


def _delta_age_hours(p: Path) -> float:
    """Best-effort age based on the embedded ISO timestamp in the filename
    (e.g. agent-id-2026-05-15T21-09-27Z.json). Falls back to mtime."""
    name = p.stem
    # Filename pattern: <agent-id>-<YYYY-MM-DDTHH-MM-SSZ>
    for tail_len in (20, 19):  # with/without seconds
        ts_part = name[-tail_len:]
        try:
            normalized = ts_part.replace("T", " ").replace("Z", "")
            # Last 8 chars are HH-MM-SS, replace dashes back to colons
            head, sep, time_part = normalized.rpartition(" ")
            if sep and len(time_part) == 8 and time_part.count("-") == 2:
                time_part = time_part.replace("-", ":")
                normalized = f"{head}T{time_part}+00:00"
                parsed = dt.datetime.fromisoformat(normalized)
                now = dt.datetime.now(dt.timezone.utc)
                return (now - parsed).total_seconds() / 3600.0
        except (ValueError, IndexError):
            continue
    # Fallback: filesystem mtime
    try:
        mtime = dt.datetime.fromtimestamp(p.stat().st_mtime, tz=dt.timezone.utc)
        return (dt.datetime.now(dt.timezone.utc) - mtime).total_seconds() / 3600.0
    except OSError:
        return 0.0


def test_inbox_count_within_tolerance(canonical_inbox):
    """No more than INFLIGHT_TOLERANCE undrained deltas."""
    if not canonical_inbox.exists():
        # Inbox dir missing entirely = no work, pass.
        return
    deltas = [p for p in canonical_inbox.glob("*.json") if p.is_file()]
    count = len(deltas)
    assert count <= INFLIGHT_TOLERANCE, (
        f"Inbox has {count} undrained deltas (tolerance {INFLIGHT_TOLERANCE}). "
        f"process_inbox.py likely not running. Run: python scripts/process_inbox.py"
    )


def test_no_stale_deltas(canonical_inbox):
    """No delta older than MAX_AGE_HOURS."""
    if not canonical_inbox.exists():
        return
    stale = []
    for p in canonical_inbox.glob("*.json"):
        if not p.is_file():
            continue
        age = _delta_age_hours(p)
        if age > MAX_AGE_HOURS:
            stale.append((p.name, round(age, 1)))
    assert not stale, (
        f"{len(stale)} delta(s) older than {MAX_AGE_HOURS}h (oldest sample: "
        f"{sorted(stale, key=lambda x: -x[1])[:3]}). Run: python scripts/process_inbox.py"
    )
