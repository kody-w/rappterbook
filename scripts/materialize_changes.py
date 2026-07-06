#!/usr/bin/env python3
"""Materialize state/changes.json from the append-only change-delta store.

The *projection* half of the append-only migration. Writers append immutable,
content-addressed change deltas to ``state/change_deltas/`` (via
``append_log.append_event``); this folds them back into the canonical
``state/changes.json`` that every reader (SDKs, frontend,
``raw.githubusercontent``) already consumes. So the write side becomes
conflict-free (disjoint delta files never collide on ``git push``) while the read
side is unchanged — backwards compatible by construction.

Deterministic + idempotent: identical deltas produce a byte-identical
``changes.json``. ``last_updated`` derives from the newest event's timestamp (not
wall-clock), so re-running with no new deltas writes nothing — no CI churn
(``rapp-static-api/1.0`` stable-write rule).

Reuses ``append_log.materialize`` for the fold. Python standard library only.

Usage:
    python scripts/materialize_changes.py            # rebuild changes.json (stable-write)
    STATE_DIR=state python scripts/materialize_changes.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from append_log import materialize
from state_io import load_json, save_json

STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))
DELTAS_DIR = STATE_DIR / "change_deltas"
CHANGES_FILE = STATE_DIR / "changes.json"
RETENTION_DAYS = 7


def build_projection(
    deltas_dir: Path | str = DELTAS_DIR,
    prune_days: int | None = RETENTION_DAYS,
    now_iso: str | None = None,
) -> dict:
    """Return the ``changes.json`` projection ``{last_updated, changes}``.

    ``last_updated`` is the newest retained event's timestamp (deterministic), so
    the same delta store always yields the same document.
    """
    events = materialize(deltas_dir, ts_key="ts", prune_days=prune_days, now_iso=now_iso)
    last_updated = events[-1].get("ts", "") if events else (now_iso or "")
    return {"last_updated": last_updated, "changes": events}


def main() -> int:
    """Rebuild changes.json from the delta store; stable-write (skip if unchanged)."""
    from state_io import now_iso

    projection = build_projection(now_iso=now_iso())
    if CHANGES_FILE.exists():
        current = load_json(CHANGES_FILE)
        if current.get("changes") == projection["changes"]:
            print("changes.json already up to date (no new deltas)")
            return 0
    save_json(CHANGES_FILE, projection)
    print(f"materialized changes.json: {len(projection['changes'])} events")
    return 0


if __name__ == "__main__":
    sys.exit(main())
