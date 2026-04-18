"""Rappter adapter — drives platform agents through the inbox."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from engine.fleet.run_frame import run_frame
from engine.registry import EngineAdapter, register


def _tick(state_dir: Path, frame: int, *, dry_run: bool = False, **opts: Any) -> dict:
    # Allow STATE_DIR override per call (run_frame reads STATE_DIR at import,
    # but we re-bind by mutating the module-level path).
    import engine.fleet.run_frame as rf
    rf.STATE_DIR = Path(state_dir)
    rf.INBOX_DIR = Path(state_dir) / "inbox"

    deltas = run_frame(
        count=int(opts.get("count", 5)),
        seed=opts.get("seed"),
        only=opts.get("agent"),
        dry_run=dry_run,
        print_only=False,
        frame=frame,
    )
    return {
        "deltas_written": len(deltas),
        "actions": [d["action"] for d in deltas],
    }


ADAPTER = register(EngineAdapter(
    name="rappter",
    description="Drive platform agents one frame at a time (writes inbox deltas).",
    domain="agents/inbox",
    tick=_tick,
    options={
        "count": "how many agents to drive (default 5)",
        "seed": "deterministic agent selection",
        "agent": "drive a single named agent",
    },
))
