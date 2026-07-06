"""Tests for materialize_changes.py — the changes.json projection.

Proves the read side is unchanged while the write side moves to append-only:
  * round-trip fidelity against the REAL state/changes.json
  * deterministic + idempotent (same deltas -> byte-identical document)
  * last_updated derives from the newest event (no wall-clock churn)
  * pruning keeps only the retention window
"""
from __future__ import annotations

import json

from append_log import decompose
from materialize_changes import build_projection


def _events(repo_root):
    return json.loads((repo_root / "state" / "changes.json").read_text())["changes"]


def test_roundtrip_reproduces_real_changes(tmp_path, repo_root):
    """Decompose the real changes.json into deltas, materialize, get it back."""
    events = _events(repo_root)
    log = tmp_path / "change_deltas"
    decompose(events, log)

    proj = build_projection(log, prune_days=None)  # fidelity: no time-based pruning
    got = {json.dumps(e, sort_keys=True) for e in proj["changes"]}
    want = {json.dumps(e, sort_keys=True) for e in events}
    assert got == want  # no event lost or invented (exact dupes collapse)
    assert proj["changes"] == sorted(proj["changes"], key=lambda e: e.get("ts", ""))


def test_last_updated_is_newest_event_not_wallclock(tmp_path):
    log = tmp_path / "d"
    decompose(
        [
            {"ts": "2026-07-01T00:00:00Z", "type": "a", "id": "1"},
            {"ts": "2026-07-03T00:00:00Z", "type": "b", "id": "2"},
        ],
        log,
    )
    proj = build_projection(log, prune_days=None)
    assert proj["last_updated"] == "2026-07-03T00:00:00Z"


def test_deterministic_idempotent(tmp_path):
    log = tmp_path / "d"
    decompose([{"ts": f"2026-07-01T00:00:{i:02d}Z", "type": "x", "id": str(i)} for i in range(10)], log)
    first = json.dumps(build_projection(log, prune_days=None), sort_keys=True)
    second = json.dumps(build_projection(log, prune_days=None), sort_keys=True)
    assert first == second


def test_prune_keeps_only_window(tmp_path):
    log = tmp_path / "d"
    decompose(
        [
            {"ts": "2026-01-01T00:00:00Z", "type": "old", "id": "1"},
            {"ts": "2026-06-30T00:00:00Z", "type": "new", "id": "2"},
        ],
        log,
    )
    proj = build_projection(log, prune_days=7, now_iso="2026-07-01T00:00:00Z")
    assert [e["type"] for e in proj["changes"]] == ["new"]


def test_empty_store_is_valid(tmp_path):
    proj = build_projection(tmp_path / "missing", prune_days=None)
    assert proj == {"last_updated": "", "changes": []}
