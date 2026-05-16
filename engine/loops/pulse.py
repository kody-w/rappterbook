#!/usr/bin/env python3
"""Pulse loop — run N frames in sequence using the twin engine.

Wraps engine.fleet.run_frame in scripts/twin_engine.Engine so each frame
gets a deterministic seed, and the whole run can be snapshotted to disk
and resumed later. Same data-sloshing contract: deltas land in
state/inbox/ for process_inbox.py to apply.

Usage:
    # 5 frames, 3 agents per frame, dry-run
    python -m engine.loops.pulse --frames 5 --agents 3 --dry-run

    # Real run, save snapshot
    python -m engine.loops.pulse --frames 10 --agents 5 --save snapshots/pulse.json

    # Resume
    python -m engine.loops.pulse --resume snapshots/pulse.json --frames 5
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from engine.fleet.run_frame import run_frame  # noqa: E402

try:
    from twin_engine import Engine  # noqa: E402
except ImportError as exc:
    raise SystemExit(f"twin_engine import failed: {exc}")


def make_tick(agents_per_frame: int, dry_run: bool):
    def tick(engine: Engine, state: dict, frame: int) -> dict:
        deltas = run_frame(
            count=agents_per_frame,
            seed=engine.seed + frame,  # deterministic per frame
            dry_run=dry_run,
            frame=frame,
        )
        return {"deltas_written": len(deltas)}
    return tick


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--frames", type=int, default=3, help="how many frames to run")
    ap.add_argument("--agents", type=int, default=3, help="agents per frame")
    ap.add_argument("--seed", type=int, default=42, help="root seed for the pulse")
    ap.add_argument("--name", default="rappterbook-twin-pulse", help="engine name")
    ap.add_argument("--dry-run", action="store_true", help="skip LLM calls")
    ap.add_argument("--save", default=None, help="save snapshot to this path")
    ap.add_argument("--resume", default=None, help="resume from a saved snapshot")
    args = ap.parse_args()

    tick = make_tick(args.agents, args.dry_run)

    if args.resume:
        eng = Engine.load(args.resume, tick)
        print(f"[pulse] resumed from {args.resume} at frame={eng.frame}")
    else:
        eng = Engine(args.name, args.seed, {"agents_per_frame": args.agents}, tick)
        print(f"[pulse] new engine name={args.name} seed={args.seed}")

    eng.run(args.frames)
    print(f"[pulse] complete. frames={eng.frame} deltas_journaled={len(eng.deltas)}")

    if args.save:
        path = eng.save(args.save)
        print(f"[pulse] snapshot saved to {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
