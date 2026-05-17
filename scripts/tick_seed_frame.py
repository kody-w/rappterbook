#!/usr/bin/env python3
"""tick_seed_frame.py — Bumps state/seeds.json active.frames_active by 1.
Idempotent within a single second window."""
from __future__ import annotations
import json, sys
from datetime import datetime, timezone
from pathlib import Path

STATE = Path("/Users/kodyw/Projects/rappterbook/state/seeds.json")


def main() -> int:
    if not STATE.exists():
        return 1
    data = json.loads(STATE.read_text())
    active = data.get("active") or {}
    if not active or not active.get("id"):
        return 0
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    if active.get("_last_tick") == now:
        return 0
    cur = int(active.get("frames_active") or 0)
    active["frames_active"] = cur + 1
    active["_last_tick"] = now
    data["active"] = active
    STATE.write_text(json.dumps(data, indent=2))
    print(f"tick {active.get('id')}: {cur} -> {cur + 1}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
