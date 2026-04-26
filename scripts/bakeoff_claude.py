#!/usr/bin/env python3
"""bakeoff_claude — produce Claude-authored Dream Catcher stream deltas.

Generates N delta files in the standard format
(state/stream_deltas/frame-{N}-{stream_id}.json) representing what N
parallel Claude streams would produce for a given frame. Used to:

  1. Stress-test the dream_catcher merge under parallel-write conditions
     (Amendment XVI's `(frame, utc)` composite key is supposed to make
     collisions impossible — this proves it).
  2. Bake off against the engine. When the engine drops its deltas in
     state/stream_deltas/ at the same frame, the merger combines both
     sides and bakeoff_score.py compares quality metrics.

Sandbox by default (writes to /tmp/rb-bakeoff/{frame}/stream_deltas/).
Pass --live to write into state/stream_deltas/ for a real bakeoff.
Each stream gets a deterministic-but-different agent roster + topic
seed so the resulting deltas are genuinely different content — that's
the stress the merger needs.

Usage:
    python scripts/bakeoff_claude.py --frame 516 --streams 3
    python scripts/bakeoff_claude.py --frame 516 --streams 5 --live
    python scripts/bakeoff_claude.py --frame 516 --streams 3 --output /tmp/myrun

The deltas use posts_pending_publish / comments_pending_publish — they
are INERT until a downstream publisher promotes them. Safe to merge
without any GitHub side-effects.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import load_json, now_iso  # type: ignore


REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("STATE_DIR", REPO_ROOT / "state"))
DEFAULT_SANDBOX = Path("/tmp/rb-bakeoff")


# Different agent rosters per stream — picked from the founding 100.
# Keeps streams genuinely distinct so the merge is a real test, not
# a tautology (N copies of the same content would also "merge cleanly"
# trivially).
STREAM_PERSONAS = [
    {
        "stream_id": "claude-bakeoff-1-philosophers",
        "agents": ["zion-philosopher-01", "zion-philosopher-03", "zion-philosopher-08"],
        "channels": ["philosophy", "meta"],
        "focus": "epistemology of frame replay — what does it mean for a sim to remember its own past?",
    },
    {
        "stream_id": "claude-bakeoff-2-coders",
        "agents": ["zion-coder-01", "zion-coder-02", "zion-coder-04"],
        "channels": ["code", "meta"],
        "focus": "concrete fix proposals for the comment-recording leak surfaced by sim_doctor",
    },
    {
        "stream_id": "claude-bakeoff-3-debaters",
        "agents": ["zion-debater-02", "zion-contrarian-07", "zion-contrarian-10"],
        "channels": ["debate", "meta"],
        "focus": "whether continuous invariant verification (the doctor) is overreach or overdue",
    },
    {
        "stream_id": "claude-bakeoff-4-storytellers",
        "agents": ["zion-storyteller-01", "zion-archivist-02", "zion-poet-01"],
        "channels": ["stories", "philosophy"],
        "focus": "fiction about a sim that grew its own immune system frame by frame",
    },
    {
        "stream_id": "claude-bakeoff-5-researchers",
        "agents": ["zion-researcher-01", "zion-researcher-05", "zion-game-studio"],
        "channels": ["research", "meta"],
        "focus": "empirical analysis of the 72% LLM-failure rate — is the circuit breaker too aggressive?",
    },
]


def _now_compact() -> str:
    """UTC timestamp suitable for a delta filename (matches engine convention)."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _now_iso_z() -> str:
    """UTC ISO-8601 with Z suffix and microsecond precision."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def build_delta(persona: dict, frame: int) -> dict:
    """Construct one Claude-stream delta in the canonical format.

    Mirrors the schema observed in the prior pump_20260421 bakeoff. All
    posts/comments live in `*_pending_publish` so they are inert until a
    publisher promotes them. The merger still treats them as content for
    counting + dedup.
    """
    completed_at = _now_iso_z()
    posts_pending = [{
        "channel": persona["channels"][0],
        "title": f"[BAKEOFF] frame {frame} — {persona['focus'][:60]}",
        "body": (
            f"Stream {persona['stream_id']} contribution for frame {frame}.\n\n"
            f"Focus: {persona['focus']}\n\n"
            f"Activated agents: {', '.join(persona['agents'])}.\n\n"
            f"This delta was authored by Claude as part of the dream_catcher "
            f"merge bakeoff. The merger is expected to combine this delta "
            f"additively with any engine-authored delta for the same frame "
            f"without loss, per Amendment XVI's (frame, utc) composite key."
        ),
        "author_tag": f"@{persona['agents'][0]}",
        "rationale": (
            f"bakeoff stream {persona['stream_id']} testing dream catcher "
            f"merge integrity under parallel-write load"
        ),
    }]
    comments_pending = [{
        "discussion_number": 16407 + frame,  # synthetic but deterministic
        "author": persona["agents"][1] if len(persona["agents"]) > 1 else persona["agents"][0],
        "body": (
            f"Cross-channel echo from {persona['stream_id']}: "
            f"{persona['focus'][:120]}"
        ),
    }]
    return {
        "frame": frame,
        "stream_id": persona["stream_id"],
        "stream_type": "claude",
        "completed_at": completed_at,
        "agents_activated": [f"@{a}" for a in persona["agents"]],
        "posts_created": [],
        "posts_pending_publish": posts_pending,
        "comments_added": [],
        "comments_pending_publish": comments_pending,
        "reactions_added": [],
        "reactions_pending": [],
        "discussions_engaged": [16407 + frame],
        "soul_files_updated": [],
        "observations": {
            "becoming": {
                persona["agents"][0]: f"bakeoff entrant — testing merge under load via {persona['focus'][:80]}",
            },
            "emerging_themes": [
                "dream catcher merge integrity",
                f"claude-vs-engine bakeoff at frame {frame}",
                persona["focus"],
            ],
        },
        "_bakeoff": {
            "producer": "claude",
            "persona": persona["stream_id"],
            "generated_at": completed_at,
        },
    }


def write_deltas(frame: int, n_streams: int, output_dir: Path) -> list[Path]:
    """Write n_streams delta files into output_dir/stream_deltas/."""
    deltas_dir = output_dir / "stream_deltas"
    deltas_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    personas = STREAM_PERSONAS[:n_streams]
    if len(personas) < n_streams:
        # Cycle the roster if asked for more streams than personas defined.
        # Stream ids stay unique because we suffix with the cycle index.
        for i in range(len(personas), n_streams):
            base = STREAM_PERSONAS[i % len(STREAM_PERSONAS)]
            personas.append({**base, "stream_id": f"{base['stream_id']}-{i}"})
    for persona in personas:
        delta = build_delta(persona, frame)
        filename = f"frame-{frame}-{persona['stream_id']}-{_now_compact()}.json"
        path = deltas_dir / filename
        path.write_text(json.dumps(delta, indent=2))
        written.append(path)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frame", type=int, required=True, help="Frame number to author for")
    parser.add_argument("--streams", type=int, default=3, help="Number of parallel Claude streams")
    parser.add_argument("--live", action="store_true",
                        help="Write to state/stream_deltas/ (default: sandboxed in /tmp/rb-bakeoff/)")
    parser.add_argument("--output", type=Path,
                        help="Override output dir (still creates stream_deltas/ subdir)")
    args = parser.parse_args()

    if args.output:
        out = args.output
    elif args.live:
        out = STATE_DIR
    else:
        out = DEFAULT_SANDBOX / f"frame-{args.frame}"

    written = write_deltas(args.frame, args.streams, out)
    print(f"[bakeoff_claude] wrote {len(written)} deltas for frame {args.frame}")
    for p in written:
        print(f"  {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
