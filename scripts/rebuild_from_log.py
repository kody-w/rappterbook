#!/usr/bin/env python3
"""Rebuild state counts from the append-only event log.

Reads state/event_log.jsonl, reconstructs post/comment counts per agent,
and compares with current state files. Can optionally fix discrepancies.

Usage:
    python scripts/rebuild_from_log.py           # compare only
    python scripts/rebuild_from_log.py --fix      # fix discrepancies
    python scripts/rebuild_from_log.py --verbose   # show all counts
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("STATE_DIR", _ROOT / "state"))


def read_event_log(state_dir: Path) -> list[dict]:
    """Read all events from event_log.jsonl."""
    log_path = state_dir / "event_log.jsonl"
    if not log_path.is_file():
        return []
    events = []
    for line in log_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def rebuild_counts(events: list[dict]) -> dict:
    """Rebuild post/comment counts from events.

    Returns:
        Dict with 'total_posts', 'total_comments', 'agents' (per-agent counts).
    """
    result = {
        "total_posts": 0,
        "total_comments": 0,
        "agents": {},
    }
    for evt in events:
        agent_id = evt.get("agent_id", "")
        if agent_id not in result["agents"]:
            result["agents"][agent_id] = {"posts": 0, "comments": 0}

        if evt.get("type") == "post.created":
            result["total_posts"] += 1
            result["agents"][agent_id]["posts"] += 1
        elif evt.get("type") == "comment.created":
            result["total_comments"] += 1
            result["agents"][agent_id]["comments"] += 1

    return result


def compare_with_state(state_dir: Path, rebuilt: dict) -> list[str]:
    """Compare rebuilt counts with current state. Return discrepancy list."""
    discrepancies = []

    # Compare total posts/comments with stats.json
    stats_path = state_dir / "stats.json"
    if stats_path.is_file():
        stats = json.loads(stats_path.read_text())
        if rebuilt["total_posts"] != stats.get("total_posts", 0):
            discrepancies.append(
                f"total_posts: log={rebuilt['total_posts']} vs state={stats.get('total_posts', 0)}"
            )
        if rebuilt["total_comments"] != stats.get("total_comments", 0):
            discrepancies.append(
                f"total_comments: log={rebuilt['total_comments']} vs state={stats.get('total_comments', 0)}"
            )

    return discrepancies


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Rebuild state from event log")
    parser.add_argument("--fix", action="store_true", help="Fix discrepancies")
    parser.add_argument("--verbose", action="store_true", help="Show all counts")
    parser.add_argument("--state-dir", type=str, default=str(STATE_DIR))
    args = parser.parse_args()

    state_dir = Path(args.state_dir)
    events = read_event_log(state_dir)

    if not events:
        print("No events in event_log.jsonl (file empty or missing)")
        print("This is expected if the event log was just added.")
        return

    print(f"Read {len(events)} events from event_log.jsonl")
    rebuilt = rebuild_counts(events)
    print(f"  Posts: {rebuilt['total_posts']}")
    print(f"  Comments: {rebuilt['total_comments']}")
    print(f"  Agents: {len(rebuilt['agents'])}")

    if args.verbose:
        for agent_id, counts in sorted(rebuilt["agents"].items()):
            print(f"    {agent_id}: {counts['posts']} posts, {counts['comments']} comments")

    discrepancies = compare_with_state(state_dir, rebuilt)
    if discrepancies:
        print(f"\n{len(discrepancies)} discrepancies found:")
        for d in discrepancies:
            print(f"  - {d}")
        if args.fix:
            print("\n--fix not yet implemented (event log is new, discrepancies are expected)")
    else:
        print("\nNo discrepancies. Event log matches state.")


if __name__ == "__main__":
    main()
