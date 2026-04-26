#!/usr/bin/env python3
"""bakeoff_score — compare quality metrics across producers in a bakeoff.

Reads stream deltas for a frame and groups them by `stream_type`
(claude, copilot, manual, engine, etc). For each producer group, reports:

  - streams         : how many parallel streams that producer ran
  - agents/stream   : average agents activated per stream
  - posts/stream    : average posts (created or pending)
  - comments/stream : average comments (added or pending)
  - dups_dropped    : how many of this producer's comments were duplicates
                      that the merger had to drop (lower = cleaner output)
  - agent_diversity : unique agents across all this producer's streams /
                      total slots (1.0 = no overlap, 0.1 = same agents
                      reused everywhere)

Then prints a head-to-head ranking on each metric. The bakeoff is
informative, not normative — there's no single "winner", but the
metrics surface where each producer is strong vs weak.

Usage:
    python scripts/bakeoff_score.py --frame 516
    python scripts/bakeoff_score.py --frame 516 --dir /tmp/rb-bakeoff/frame-516
    python scripts/bakeoff_score.py --frame 516 --json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "deploy"))

from merge_workers import discover_deltas  # type: ignore


def _comment_fp(c: dict) -> str:
    """Same fingerprint the merger uses for dedup — discussion+author+body[:100]."""
    return (
        f"{c.get('discussion', c.get('discussion_number', ''))}-"
        f"{c.get('author', '')}-"
        f"{str(c.get('body', ''))[:100]}"
    )


def score_producer(deltas: list[dict]) -> dict:
    """Compute quality metrics for one producer's deltas."""
    n = len(deltas)
    if n == 0:
        return {"streams": 0}

    agents_per_stream = []
    posts_per_stream = []
    comments_per_stream = []
    all_agents: list[str] = []
    all_comment_fps: list[str] = []

    for d in deltas:
        agents = d.get("agents_activated", []) or []
        posts = (d.get("posts_created", []) or []) + (d.get("posts_pending_publish", []) or [])
        comments = (d.get("comments_added", []) or []) + (d.get("comments_pending_publish", []) or [])
        agents_per_stream.append(len(agents))
        posts_per_stream.append(len(posts))
        comments_per_stream.append(len(comments))
        all_agents.extend(agents)
        all_comment_fps.extend(_comment_fp(c) for c in comments)

    total_agent_slots = len(all_agents) or 1
    unique_agents = len(set(all_agents))
    agent_diversity = unique_agents / total_agent_slots

    total_comments = len(all_comment_fps) or 1
    unique_comments = len(set(all_comment_fps))
    dups_dropped = total_comments - unique_comments

    return {
        "streams": n,
        "agents_per_stream": round(sum(agents_per_stream) / n, 1),
        "posts_per_stream": round(sum(posts_per_stream) / n, 1),
        "comments_per_stream": round(sum(comments_per_stream) / n, 1),
        "agent_diversity": round(agent_diversity, 2),
        "unique_agents": unique_agents,
        "total_agent_slots": total_agent_slots,
        "dups_dropped": dups_dropped,
    }


def score_all(deltas: list[dict]) -> dict[str, dict]:
    """Group deltas by stream_type, score each group."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for d in deltas:
        groups[d.get("stream_type", "unknown")].append(d)
    return {producer: score_producer(ds) for producer, ds in groups.items()}


def print_scoreboard(scores: dict[str, dict]) -> None:
    """Tabular comparison across producers."""
    if not scores:
        print("(no deltas)")
        return

    metrics = [
        ("streams", "streams"),
        ("agents_per_stream", "agents/strm"),
        ("posts_per_stream", "posts/strm"),
        ("comments_per_stream", "comm/strm"),
        ("agent_diversity", "diversity"),
        ("dups_dropped", "dup-drop"),
    ]
    producers = sorted(scores.keys())

    # Header
    print(f"{'metric':<18}  " + "  ".join(f"{p:>14}" for p in producers))
    print("-" * (20 + 16 * len(producers)))
    for key, label in metrics:
        row = f"{label:<18}  " + "  ".join(
            f"{scores[p].get(key, '—'):>14}" for p in producers
        )
        print(row)
    print()

    # Per-metric winners
    print("winners per metric (informative, not normative):")
    for key, label in metrics:
        if key in ("streams", "dups_dropped"):
            # higher streams = more parallelism (informative); higher dups = WORSE
            if key == "dups_dropped":
                sortable = sorted(producers, key=lambda p: scores[p].get(key, 1e9))
                arrow = "fewer dropped dups (cleaner output) →"
            else:
                sortable = sorted(producers, key=lambda p: -scores[p].get(key, 0))
                arrow = "more parallel streams →"
        else:
            sortable = sorted(producers, key=lambda p: -scores[p].get(key, 0))
            arrow = f"higher {label} →"
        print(f"  {arrow:35}  {sortable[0]}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frame", type=int, required=True)
    parser.add_argument("--dir", type=Path, default=None,
                        help="State dir to scan. Default: state/ (live).")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    state_dir = args.dir if args.dir else (REPO_ROOT / "state")
    deltas = discover_deltas(state_dir, args.frame)
    scores = score_all(deltas)

    if args.json:
        print(json.dumps({"frame": args.frame, "scores": scores}, indent=2))
    else:
        print(f"=== bakeoff_score · frame {args.frame} ===\n")
        print_scoreboard(scores)
    return 0


if __name__ == "__main__":
    sys.exit(main())
