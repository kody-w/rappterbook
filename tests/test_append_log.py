"""Tests for the append-only, content-addressed event log (scripts/append_log.py).

Proves the properties the platform's scalable write path depends on:
  * round-trip fidelity — decompose a shared-JSON list into deltas, materialize,
    get the same events back (verified against the REAL state/changes.json)
  * idempotency — appending an identical event twice writes one file; two
    concurrent writers of the same event never conflict
  * append-only — the store only grows; materialize never drops an event
  * determinism — re-materializing yields byte-identical output
  * ordering + pruning
"""
from __future__ import annotations

import json

from append_log import append_event, content_id, decompose, materialize


def _canon(e: dict) -> str:
    return json.dumps(e, sort_keys=True, separators=(",", ":"))


def test_roundtrip_against_real_changes_json(tmp_path, repo_root):
    """Decompose the real changes.json into deltas and materialize it back."""
    changes = json.loads((repo_root / "state" / "changes.json").read_text())["changes"]
    log = tmp_path / "change_deltas"

    written = decompose(changes, log)
    assert written == len(changes)

    got = materialize(log)
    # No event lost, none invented; dedup-by-content only removes exact dupes.
    assert {_canon(e) for e in got} == {_canon(e) for e in changes}
    # Output is ordered by timestamp.
    assert [e.get("ts", "") for e in got] == sorted(e.get("ts", "") for e in got)


def test_identical_event_is_written_once(tmp_path):
    """Two writers appending the same event collide on one content-addressed file."""
    log = tmp_path / "log"
    event = {"ts": "2026-07-01T00:00:00Z", "type": "heartbeat", "id": "agent-1"}
    p1 = append_event(log, event)
    p2 = append_event(log, dict(event))  # same content, different dict object
    assert p1 == p2
    assert len(list(log.glob("*.json"))) == 1
    assert len(materialize(log)) == 1


def test_distinct_events_never_share_a_file(tmp_path):
    """Disjoint events land in disjoint files (this is what makes pushes conflict-free)."""
    log = tmp_path / "log"
    paths = {
        append_event(log, {"ts": "2026-07-01T00:00:00Z", "type": "heartbeat", "id": f"a-{i}"})
        for i in range(50)
    }
    assert len(paths) == 50
    assert len(materialize(log)) == 50


def test_materialize_is_deterministic_and_idempotent(tmp_path):
    """Re-materializing the same store yields byte-identical output."""
    log = tmp_path / "log"
    for i in range(20):
        append_event(log, {"ts": f"2026-07-01T00:00:{i:02d}Z", "type": "poke", "id": str(i)})
    first = json.dumps(materialize(log), sort_keys=True)
    second = json.dumps(materialize(log), sort_keys=True)
    assert first == second


def test_append_only_growth(tmp_path):
    """The store only grows; a later materialize is a superset of an earlier one."""
    log = tmp_path / "log"
    append_event(log, {"ts": "2026-07-01T00:00:00Z", "type": "x", "id": "1"})
    before = {content_id(e) for e in materialize(log)}
    append_event(log, {"ts": "2026-07-01T00:00:01Z", "type": "x", "id": "2"})
    after = {content_id(e) for e in materialize(log)}
    assert before < after


def test_prune_days_drops_old_events(tmp_path):
    """Pruning keeps only events within the window, relative to a fixed now."""
    log = tmp_path / "log"
    append_event(log, {"ts": "2026-01-01T00:00:00Z", "type": "old", "id": "1"})
    append_event(log, {"ts": "2026-06-30T00:00:00Z", "type": "new", "id": "2"})
    kept = materialize(log, prune_days=7, now_iso="2026-07-01T00:00:00Z")
    assert [e["type"] for e in kept] == ["new"]


def test_corrupt_delta_is_skipped(tmp_path):
    """A malformed delta file is ignored, never crashing the materializer."""
    log = tmp_path / "log"
    log.mkdir()
    (log / "20260701T000000-deadbeef.json").write_text("{not json")
    append_event(log, {"ts": "2026-07-01T00:00:00Z", "type": "ok", "id": "1"})
    assert len(materialize(log)) == 1
