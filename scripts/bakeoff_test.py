#!/usr/bin/env python3
"""bakeoff_test — verify dream_catcher merge integrity under parallel writes.

Reads stream deltas from a directory (sandbox or live state/stream_deltas/),
runs the merge logic from scripts/deploy/merge_workers.py, and reports:

  - inputs:    N deltas in, total agents/posts/comments contributed
  - merged:    after dedup + conflict resolution
  - integrity: anything dropped? any composite-key collisions?
  - per-stream contribution: who contributed what

The point: prove (or disprove) Amendment XVI's claim that parallel
streams writing the same frame merge additively without loss when keyed
by (frame, utc).

Usage:
    python scripts/bakeoff_test.py --frame 516
    python scripts/bakeoff_test.py --frame 516 --dir /tmp/rb-bakeoff/frame-516
    python scripts/bakeoff_test.py --frame 516 --json
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

from merge_workers import (  # type: ignore
    discover_deltas,
    group_by_worker,
    merge_all_deltas,
    resolve_conflicts,
)


def collect_pending(deltas: list[dict]) -> tuple[list[dict], list[dict]]:
    """Sum posts_pending_publish + comments_pending_publish across all deltas.

    The merger's resolve_conflicts only deduplicates posts_created /
    comments_added. For bakeoff tests we mostly use _pending_publish so
    nothing actually publishes; this aggregator still gives us a count.
    """
    posts: list[dict] = []
    comments: list[dict] = []
    for d in deltas:
        posts.extend(d.get("posts_created", []) or [])
        posts.extend(d.get("posts_pending_publish", []) or [])
        comments.extend(d.get("comments_added", []) or [])
        comments.extend(d.get("comments_pending_publish", []) or [])
    return posts, comments


def integrity_report(frame: int, deltas: list[dict]) -> dict:
    """Compute the integrity stats this script reports on."""
    by_worker = group_by_worker(deltas)
    posts_in, comments_in = collect_pending(deltas)
    merged = merge_all_deltas(deltas)
    resolved_posts, resolved_comments = resolve_conflicts(
        merged.get("posts_created", []),
        # merge_all_deltas already accumulated comments into a list; pull it
        # back via the stream summaries to feed resolve_conflicts.
        [c for d in deltas for c in d.get("comments_added", []) or []],
    )

    # Composite-key uniqueness: (frame, completed_at) per stream
    keys = [(d.get("frame"), d.get("completed_at"), d.get("stream_id")) for d in deltas]
    duplicate_keys = [k for k in keys if keys.count(k) > 1]

    # Per-stream contribution
    per_stream: dict[str, dict] = {}
    for d in deltas:
        sid = d.get("stream_id", "unknown")
        per_stream[sid] = {
            "agents_activated": len(d.get("agents_activated", []) or []),
            "posts_total": len((d.get("posts_created", []) or []) + (d.get("posts_pending_publish", []) or [])),
            "comments_total": len((d.get("comments_added", []) or []) + (d.get("comments_pending_publish", []) or [])),
            "stream_type": d.get("stream_type", "?"),
            "completed_at": d.get("completed_at"),
            "worker_id": d.get("_worker_id", "primary"),
        }

    workers_to_streams = {w: [d.get("stream_id") for d in ds] for w, ds in by_worker.items()}

    return {
        "frame": frame,
        "deltas_in": len(deltas),
        "workers": list(by_worker.keys()),
        "workers_to_streams": workers_to_streams,
        "inputs": {
            "agents_activated": len(merged.get("agents_activated", [])),
            "posts_pending_or_created": len(posts_in),
            "comments_pending_or_added": len(comments_in),
        },
        "merged": {
            "agents_activated": len(set(merged.get("agents_activated", []))),
            "posts_after_dedup": len(resolved_posts),
            "comments_after_dedup": len(resolved_comments),
            "discussions_engaged": len(merged.get("discussions_engaged", [])),
        },
        "integrity": {
            "duplicate_composite_keys": duplicate_keys,
            "all_unique_keys": not duplicate_keys,
            "posts_lost_to_dedup": max(
                0, len(merged.get("posts_created", [])) - len(resolved_posts)
            ),
            "comments_lost_to_dedup": max(
                0,
                len([c for d in deltas for c in d.get("comments_added", []) or []])
                - len(resolved_comments),
            ),
        },
        "per_stream": per_stream,
    }


def print_report(report: dict) -> None:
    """Human-friendly printout of the integrity report."""
    print(f"=== bakeoff_test · frame {report['frame']} ===\n")
    print(f"  deltas in:       {report['deltas_in']}")
    print(f"  workers:         {len(report['workers'])} ({', '.join(report['workers']) or '—'})")
    print()
    print("  INPUTS (sum across all streams)")
    for k, v in report["inputs"].items():
        print(f"    {k:32}  {v}")
    print()
    print("  MERGED (after dedup + conflict resolution)")
    for k, v in report["merged"].items():
        print(f"    {k:32}  {v}")
    print()
    print("  INTEGRITY")
    integrity = report["integrity"]
    print(f"    all_unique_composite_keys      {integrity['all_unique_keys']}")
    if integrity["duplicate_composite_keys"]:
        print(f"    DUPLICATE KEYS DETECTED:")
        for k in integrity["duplicate_composite_keys"]:
            print(f"      {k}")
    print(f"    posts_lost_to_dedup            {integrity['posts_lost_to_dedup']}")
    print(f"    comments_lost_to_dedup         {integrity['comments_lost_to_dedup']}")
    print()
    print("  PER-STREAM CONTRIBUTION")
    for sid, stats in report["per_stream"].items():
        print(f"    {sid:50}  agents={stats['agents_activated']:>2}  "
              f"posts={stats['posts_total']:>2}  comments={stats['comments_total']:>2}  "
              f"({stats['stream_type']})")
    print()
    verdict = "PASS" if integrity["all_unique_keys"] and integrity["posts_lost_to_dedup"] == 0 else "FAIL"
    print(f"=== verdict: {verdict} ===")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frame", type=int, required=True)
    parser.add_argument("--dir", type=Path, default=None,
                        help="State dir to scan. Default: state/ (live).")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON only")
    args = parser.parse_args()

    state_dir = args.dir if args.dir else (REPO_ROOT / "state")
    deltas = discover_deltas(state_dir, args.frame)

    report = integrity_report(args.frame, deltas)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print_report(report)
    return 0 if report["integrity"]["all_unique_keys"] else 1


if __name__ == "__main__":
    sys.exit(main())
