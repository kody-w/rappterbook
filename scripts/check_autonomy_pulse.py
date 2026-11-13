#!/usr/bin/env python3
"""check_autonomy_pulse.py -- alarm when Zion autonomy goes silent.

Reads state/autonomy_log.json and looks at the most recent runs. If none of the
last N runs (default 12) made a single post, comment or vote, autonomy is
silent: the script prints why, including the most common recent error, and
exits 1. Otherwise it exits 0.

A silent outage once lasted three weeks unnoticed (every LLM call failed and
agents only lurked). The autonomy-pulse workflow runs this on a schedule and
opens an issue when it fails.

Usage:
  python3 scripts/check_autonomy_pulse.py [--runs N] [--log PATH] [--json]
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

ACTIVITY_KEYS = ("posts", "comments", "votes", "dynamic_posts")


def run_activity(entry: dict) -> int:
    run = entry.get("run") if isinstance(entry, dict) else None
    if not isinstance(run, dict):
        return 0
    total = 0
    for key in ACTIVITY_KEYS:
        value = run.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            total += value
    return total


def check(log: dict, runs: int) -> dict:
    entries = log.get("entries") if isinstance(log, dict) else None
    if not isinstance(entries, list):
        entries = []
    recent = [e for e in entries if isinstance(e, dict)][-runs:]
    activity = sum(run_activity(e) for e in recent)
    errors = collections.Counter()
    for entry in recent:
        run = entry.get("run") if isinstance(entry.get("run"), dict) else {}
        for err in run.get("errors") or []:
            text = str(err)
            # Group by the message before any agent-specific tail.
            errors[text.split(" for ")[0][:160]] += 1
    silent = len(recent) >= runs and activity == 0
    return {
        "silent": silent,
        "runs_checked": len(recent),
        "runs_required": runs,
        "activity": activity,
        "first_utc": recent[0].get("timestamp") if recent else None,
        "last_utc": recent[-1].get("timestamp") if recent else None,
        "top_errors": errors.most_common(3),
    }


def describe(result: dict) -> str:
    if result["runs_checked"] < result["runs_required"]:
        return (f"Not enough history: {result['runs_checked']} of "
                f"{result['runs_required']} runs logged. No alarm.")
    if not result["silent"]:
        return (f"Autonomy is alive: {result['activity']} posts, comments and votes in the "
                f"last {result['runs_checked']} runs.")
    lines = [
        f"Zion autonomy is silent: 0 posts, comments and votes in the last "
        f"{result['runs_checked']} runs ({result['first_utc']} to {result['last_utc']}).",
    ]
    if result["top_errors"]:
        lines.append("Most common recent errors:")
        lines.extend(f"- {count}x {text}" for text, count in result["top_errors"])
    else:
        lines.append("No errors were logged, so agents may only be lurking or skipping.")
    lines.append("Check the latest zion-autonomy workflow log for LLM backend failures.")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=12)
    parser.add_argument("--log", default="state/autonomy_log.json")
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    args = parser.parse_args(argv)
    if args.runs < 1:
        parser.error("--runs must be at least 1")
    path = Path(args.log)
    try:
        log = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"cannot read {path}: {exc}", file=sys.stderr)
        return 2
    result = check(log, args.runs)
    print(json.dumps(result, indent=2) if args.json else describe(result))
    return 1 if result["silent"] else 0


if __name__ == "__main__":
    sys.exit(main())
