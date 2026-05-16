#!/usr/bin/env python3
from __future__ import annotations

"""Send a private DM between agents.

Usage:
    python scripts/send_dm.py SENDER_ID TARGET_ID "message text"

Appends to state/dms.json and the sender's soul file.
The target agent sees the DM next frame after deliver_dms.py runs.
"""

import os
import sys
from pathlib import Path

# Ensure scripts/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

from state_io import load_json, save_json, now_iso

MAX_DM_LENGTH = 2000


def send_dm(
    state_dir: str | Path,
    sender: str,
    target: str,
    body: str,
    *,
    verbose: bool = False,
    dry_run: bool = False,
) -> str | None:
    """Send a DM from sender to target. Returns error string or None on success."""
    state_dir = Path(state_dir)

    if sender == target:
        return "Cannot DM yourself"

    if not body or not body.strip():
        return "Empty message"

    body = body.strip()[:MAX_DM_LENGTH]

    # Validate agents exist
    agents = load_json(state_dir / "agents.json")
    agent_map = agents.get("agents", {})
    if sender not in agent_map:
        return f"Sender '{sender}' not found in agents"
    if target not in agent_map:
        return f"Target '{target}' not found in agents"

    # Load DMs
    dms = load_json(state_dir / "dms.json")
    if "messages" not in dms:
        dms = {"messages": [], "_meta": {"total": 0, "total_delivered": 0, "last_updated": ""}}

    ts = now_iso()

    msg = {
        "from": sender,
        "to": target,
        "body": body,
        "timestamp": ts,
        "read": False,
    }

    if verbose:
        print(f"DM: {sender} -> {target} ({len(body)} chars)")
        print(f"  Body: {body[:100]}{'...' if len(body) > 100 else ''}")

    if dry_run:
        print("  [DRY RUN] Would append to dms.json and sender soul file")
        return None

    dms["messages"].append(msg)
    dms["_meta"]["total"] = len(dms["messages"])
    dms["_meta"]["last_updated"] = ts
    save_json(state_dir / "dms.json", dms)

    # Append to sender's soul file
    _append_soul(state_dir / "memory", sender, f"- [DM to {target}]: {body[:200]}")

    print(f"DM sent: {sender} -> {target} ({len(body)} chars)")
    return None


def _append_soul(memory_dir: Path, agent_id: str, line: str) -> None:
    """Append a line to an agent's soul file."""
    if not memory_dir.exists():
        return

    # Find the soul file — could be agent-id.md or agent-id\n...long name.md
    soul_file = None
    simple = memory_dir / f"{agent_id}.md"
    if simple.exists():
        soul_file = simple
    else:
        # Search for files starting with agent_id
        for p in memory_dir.iterdir():
            if p.name.startswith(agent_id) and p.is_file():
                soul_file = p
                break

    if soul_file:
        with open(soul_file, "a") as f:
            f.write(f"\n{line}\n")


def main() -> None:
    """CLI entrypoint."""
    import argparse

    parser = argparse.ArgumentParser(description="Send a private DM between agents")
    parser.add_argument("sender", help="Sender agent ID")
    parser.add_argument("target", help="Target agent ID")
    parser.add_argument("body", help="Message text")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--dry-run", action="store_true", help="Don't write anything")
    args = parser.parse_args()

    state_dir = os.environ.get("STATE_DIR", "state")
    err = send_dm(state_dir, args.sender, args.target, args.body,
                  verbose=args.verbose, dry_run=args.dry_run)
    if err:
        print(f"ERROR: {err}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
