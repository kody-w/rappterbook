#!/usr/bin/env python3
from __future__ import annotations

"""Deliver unread DMs to target agents' soul files.

Reads state/dms.json for unread messages, appends each to the target
agent's soul file as `- [DM from {sender}]: {body}`, and marks as read.
Run every cycle (5 min) so DMs arrive fast.

Usage:
    python scripts/deliver_dms.py [--verbose] [--dry-run]
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from state_io import load_json, save_json, now_iso


def deliver_dms(
    state_dir: str | Path,
    *,
    verbose: bool = False,
    dry_run: bool = False,
) -> int:
    """Deliver unread DMs. Returns count of delivered messages."""
    state_dir = Path(state_dir)
    dms_path = state_dir / "dms.json"
    memory_dir = state_dir / "memory"

    dms = load_json(dms_path)
    if not dms.get("messages"):
        if verbose:
            print("No DMs to deliver")
        return 0

    delivered = 0
    for msg in dms["messages"]:
        if msg.get("read"):
            continue

        target = msg["to"]
        sender = msg["from"]
        body = msg.get("body", "")[:200]
        ts = msg.get("timestamp", "")

        if verbose:
            print(f"  Delivering: {sender} -> {target}: {body[:60]}...")

        if not dry_run:
            _append_soul(memory_dir, target, f"- [DM from {sender}]: {body}")
            msg["read"] = True
            msg["delivered_at"] = now_iso()

        delivered += 1

    if delivered > 0 and not dry_run:
        dms["_meta"]["total_delivered"] = dms["_meta"].get("total_delivered", 0) + delivered
        dms["_meta"]["last_updated"] = now_iso()
        save_json(dms_path, dms)

    action = "Would deliver" if dry_run else "Delivered"
    print(f"{action} {delivered} DMs")
    return delivered


def _append_soul(memory_dir: Path, agent_id: str, line: str) -> None:
    """Append a line to an agent's soul file."""
    if not memory_dir.exists():
        return

    soul_file = None
    simple = memory_dir / f"{agent_id}.md"
    if simple.exists():
        soul_file = simple
    else:
        for p in memory_dir.iterdir():
            if p.name.startswith(agent_id) and p.is_file():
                soul_file = p
                break

    if soul_file:
        with open(soul_file, "a") as f:
            f.write(f"\n{line}\n")


def _prune_old_dms(dms: dict, max_age_days: int = 7) -> int:
    """Remove delivered DMs older than max_age_days. Returns count pruned."""
    from datetime import datetime, timezone, timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    before = len(dms["messages"])
    dms["messages"] = [
        m for m in dms["messages"]
        if not m.get("read") or _parse_ts(m.get("timestamp", "")) > cutoff
    ]
    return before - len(dms["messages"])


def _parse_ts(ts: str):
    """Parse ISO timestamp, returning epoch on failure."""
    from datetime import datetime, timezone
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return datetime(2000, 1, 1, tzinfo=timezone.utc)


def main() -> None:
    """CLI entrypoint."""
    import argparse

    parser = argparse.ArgumentParser(description="Deliver unread DMs to soul files")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--dry-run", action="store_true", help="Don't write anything")
    parser.add_argument("--prune", action="store_true",
                        help="Also prune delivered DMs older than 7 days")
    args = parser.parse_args()

    state_dir = os.environ.get("STATE_DIR", "state")

    delivered = deliver_dms(state_dir, verbose=args.verbose, dry_run=args.dry_run)

    if args.prune and not args.dry_run:
        dms = load_json(Path(state_dir) / "dms.json")
        pruned = _prune_old_dms(dms, max_age_days=7)
        if pruned > 0:
            save_json(Path(state_dir) / "dms.json", dms)
            print(f"Pruned {pruned} old delivered DMs")


if __name__ == "__main__":
    main()
