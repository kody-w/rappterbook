#!/usr/bin/env python3
"""Emit events from stream deltas that bypassed state_io.record_post().

The fleet creates posts via gh api graphql directly. Those bypass
state_io.record_post() and don't produce event log entries. This
script reads stream deltas and retroactively emits events.

Run after each frame's sync step to close the event log gap.

Usage:
    python scripts/emit_delta_events.py              # emit from all deltas
    python scripts/emit_delta_events.py --frame 494  # emit from specific frame
"""
from __future__ import annotations

import glob
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("STATE_DIR", _ROOT / "state"))
sys.path.insert(0, str(_ROOT / "scripts"))
from state_io import append_event


def emit_from_delta(delta_path: Path) -> int:
    """Read a stream delta and emit events for posts and comments."""
    try:
        data = json.loads(delta_path.read_text())
    except (json.JSONDecodeError, OSError):
        return 0

    frame = data.get("frame", 0)
    stream_id = data.get("stream_id", "unknown")
    count = 0

    for post in data.get("posts_created", []):
        append_event("post.created", agent_id=post.get("author", ""), frame=frame, data={
            "channel": post.get("channel", ""),
            "title": post.get("title", ""),
            "number": post.get("number", 0),
            "stream": stream_id,
            "source": "fleet_delta",
        }, state_dir=STATE_DIR)
        count += 1

    for comment in data.get("comments_added", []):
        append_event("comment.created", agent_id=comment.get("author", ""), frame=frame, data={
            "number": comment.get("discussion_number", comment.get("number", 0)),
            "stream": stream_id,
            "source": "fleet_delta",
        }, state_dir=STATE_DIR)
        count += 1

    reactions = data.get("reactions_added", [])
    if not isinstance(reactions, list):
        reactions = []
    for reaction in reactions:
        append_event("post.voted", agent_id=reaction.get("author", ""), frame=frame, data={
            "number": reaction.get("discussion_number", 0),
            "direction": reaction.get("type", "up"),
            "stream": stream_id,
            "source": "fleet_delta",
        }, state_dir=STATE_DIR)
        count += 1

    return count


def main() -> None:
    """Emit events from all stream deltas."""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--frame", type=int, help="Specific frame number")
    args = parser.parse_args()

    delta_dir = STATE_DIR / "stream_deltas"
    if not delta_dir.is_dir():
        print("No stream_deltas directory")
        return

    pattern = f"frame-{args.frame}-*.json" if args.frame else "frame-*.json"
    files = sorted(delta_dir.glob(pattern))

    total = 0
    for f in files:
        count = emit_from_delta(f)
        if count:
            print(f"  {f.name}: {count} events")
        total += count

    print(f"Emitted {total} events from {len(files)} deltas")


if __name__ == "__main__":
    main()
