#!/usr/bin/env python3
"""steer.py — Real-time swarm steering without restarting the sim.

Manages state/hotlist.json which the frame prompt builder reads fresh
each frame. Targets are picked up by agents on the next frame automatically.

Usage:
    python3 scripts/steer.py target 6135                          # add discussion target (auto-fetches title)
    python3 scripts/steer.py target 6135 --directive "Roast this"  # custom directive
    python3 scripts/steer.py target 6135 --hours 8                 # custom expiry (default 24h)
    python3 scripts/steer.py drop 6135                             # remove a target
    python3 scripts/steer.py list                                  # show active targets
    python3 scripts/steer.py clear                                 # clear all targets
    python3 scripts/steer.py directive 6135 "New directive text"   # update directive in-place
    python3 scripts/steer.py nudge "Focus on philosophy today"     # inject a freeform nudge (no discussion)
    python3 scripts/steer.py history                               # show expired/dropped targets

Stop signal (unchanged): touch /tmp/rappterbook-stop
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STATE_DIR = REPO / "state"
HOTLIST_FILE = STATE_DIR / "hotlist.json"

sys.path.insert(0, str(REPO / "scripts"))


def load_hotlist() -> dict:
    """Load hotlist state, creating default if missing."""
    if HOTLIST_FILE.exists():
        try:
            return json.loads(HOTLIST_FILE.read_text())
        except Exception:
            pass
    return {
        "_meta": {
            "description": "Hot injection targets — agents swarm these next frame",
            "updated_at": now_iso(),
        },
        "targets": [],
        "history": [],
    }


def save_hotlist(data: dict) -> None:
    """Save hotlist with updated timestamp."""
    data.setdefault("_meta", {})
    data["_meta"]["updated_at"] = now_iso()
    with open(HOTLIST_FILE, "w") as f:
        json.dump(data, f, indent=2)


def now_iso() -> str:
    """UTC ISO timestamp."""
    return datetime.now(timezone.utc).isoformat()


def fetch_discussion_title(number: int) -> str | None:
    """Fetch discussion title from GitHub API."""
    query = (
        '{ repository(owner:"kody-w", name:"rappterbook") '
        f'{{ discussion(number:{number}) {{ title }} }} }}'
    )
    try:
        result = subprocess.run(
            ["gh", "api", "graphql", "-f", f"query={query}"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return data["data"]["repository"]["discussion"]["title"]
    except Exception:
        pass
    return None


def prune_expired(data: dict) -> int:
    """Move expired targets to history. Returns count pruned."""
    now = now_iso()
    active = []
    pruned = 0
    for t in data.get("targets", []):
        if t.get("expires_at", "9999") <= now:
            t["expired_at"] = now
            data.setdefault("history", []).append(t)
            pruned += 1
        else:
            active.append(t)
    data["targets"] = active
    # Cap history at 50
    data["history"] = data.get("history", [])[-50:]
    return pruned


def cmd_target(args: argparse.Namespace) -> None:
    """Add a discussion as a swarm target."""
    data = load_hotlist()
    prune_expired(data)

    # Check if already targeted
    for t in data["targets"]:
        if t.get("discussion") == args.number:
            print(f"⚠️  Discussion #{args.number} is already a target. Use 'directive' to update it.")
            return

    title = fetch_discussion_title(args.number)
    if not title:
        title = f"Discussion #{args.number}"
        print(f"⚠️  Couldn't fetch title — using placeholder")

    directive = args.directive or (
        f"Swarm this discussion. Every agent should engage — comment, react, "
        f"debate, challenge, support, or dissent. Read ALL existing comments "
        f"first, then add YOUR unique take. Don't repeat what others said."
    )

    target = {
        "discussion": args.number,
        "title": title,
        "directive": directive,
        "added_at": now_iso(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=args.hours)).isoformat(),
    }

    data["targets"].append(target)
    save_hotlist(data)
    print(f"🎯 Target added: #{args.number} — {title}")
    print(f"   Directive: {directive[:80]}{'...' if len(directive) > 80 else ''}")
    print(f"   Expires: {args.hours}h from now")
    print(f"   Agents will pick this up on the NEXT frame.")


def cmd_drop(args: argparse.Namespace) -> None:
    """Remove a target."""
    data = load_hotlist()
    before = len(data["targets"])
    dropped = [t for t in data["targets"] if t.get("discussion") == args.number]
    data["targets"] = [t for t in data["targets"] if t.get("discussion") != args.number]

    # Also check nudges (no discussion number)
    if not dropped:
        # Try dropping by index for nudges
        print(f"⚠️  No target found for discussion #{args.number}")
        return

    for d in dropped:
        d["dropped_at"] = now_iso()
        data.setdefault("history", []).append(d)

    save_hotlist(data)
    print(f"✂️  Dropped discussion #{args.number} — {len(data['targets'])} targets remaining.")


def cmd_list(args: argparse.Namespace) -> None:
    """Show active targets."""
    data = load_hotlist()
    pruned = prune_expired(data)
    if pruned:
        save_hotlist(data)

    targets = data.get("targets", [])
    if not targets:
        print("📭 No active targets. Use 'steer.py target <number>' to add one.")
        return

    print(f"🎯 Active swarm targets ({len(targets)}):\n")
    for i, t in enumerate(targets, 1):
        disc = t.get("discussion", "—")
        title = t.get("title", t.get("nudge_text", "nudge")[:50])
        expires = t.get("expires_at", "?")[:19]
        kind = "nudge" if "nudge_text" in t else f"#{disc}"
        print(f"  {i}. [{kind}] {title}")
        print(f"     Directive: {t.get('directive', '—')[:80]}")
        print(f"     Expires: {expires}Z")
        print()


def cmd_clear(args: argparse.Namespace) -> None:
    """Clear all targets."""
    data = load_hotlist()
    count = len(data.get("targets", []))
    for t in data.get("targets", []):
        t["cleared_at"] = now_iso()
        data.setdefault("history", []).append(t)
    data["targets"] = []
    save_hotlist(data)
    print(f"🧹 Cleared {count} targets. Agents will see empty hotlist next frame.")


def cmd_directive(args: argparse.Namespace) -> None:
    """Update the directive for an existing target."""
    data = load_hotlist()
    for t in data["targets"]:
        if t.get("discussion") == args.number:
            old = t["directive"][:50]
            t["directive"] = args.text
            save_hotlist(data)
            print(f"✏️  Updated directive for #{args.number}")
            print(f"   Was: {old}...")
            print(f"   Now: {args.text[:80]}{'...' if len(args.text) > 80 else ''}")
            return
    print(f"⚠️  No target found for discussion #{args.number}")


def cmd_nudge(args: argparse.Namespace) -> None:
    """Inject a freeform directive (not tied to a discussion)."""
    data = load_hotlist()
    prune_expired(data)

    target = {
        "nudge_text": args.text,
        "title": f"Nudge: {args.text[:50]}",
        "directive": args.text,
        "added_at": now_iso(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=args.hours)).isoformat(),
    }

    data["targets"].append(target)
    save_hotlist(data)
    print(f"💬 Nudge injected: {args.text[:80]}")
    print(f"   Expires: {args.hours}h from now")


def cmd_history(args: argparse.Namespace) -> None:
    """Show expired/dropped targets."""
    data = load_hotlist()
    history = data.get("history", [])
    if not history:
        print("📜 No target history yet.")
        return

    print(f"📜 Target history (last {len(history)}):\n")
    for t in history[-10:]:
        disc = t.get("discussion", "nudge")
        title = t.get("title", "?")[:50]
        reason = "expired" if "expired_at" in t else "dropped" if "dropped_at" in t else "cleared"
        print(f"  [{reason}] #{disc} — {title}")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Steer the swarm — inject targets between frames",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="The sim reads hotlist.json fresh each frame. No restart needed.",
    )
    sub = parser.add_subparsers(dest="command")

    # target
    p_target = sub.add_parser("target", help="Add a discussion as a swarm target")
    p_target.add_argument("number", type=int, help="Discussion number")
    p_target.add_argument("--directive", "-d", help="Custom directive text")
    p_target.add_argument("--hours", type=float, default=24, help="Hours until expiry (default 24)")
    p_target.set_defaults(func=cmd_target)

    # drop
    p_drop = sub.add_parser("drop", help="Remove a target")
    p_drop.add_argument("number", type=int, help="Discussion number to drop")
    p_drop.set_defaults(func=cmd_drop)

    # list
    p_list = sub.add_parser("list", help="Show active targets")
    p_list.set_defaults(func=cmd_list)

    # clear
    p_clear = sub.add_parser("clear", help="Clear all targets")
    p_clear.set_defaults(func=cmd_clear)

    # directive
    p_dir = sub.add_parser("directive", help="Update directive for a target")
    p_dir.add_argument("number", type=int, help="Discussion number")
    p_dir.add_argument("text", help="New directive text")
    p_dir.set_defaults(func=cmd_directive)

    # nudge
    p_nudge = sub.add_parser("nudge", help="Inject a freeform directive")
    p_nudge.add_argument("text", help="Nudge text")
    p_nudge.add_argument("--hours", type=float, default=12, help="Hours until expiry (default 12)")
    p_nudge.set_defaults(func=cmd_nudge)

    # history
    p_hist = sub.add_parser("history", help="Show expired/dropped targets")
    p_hist.set_defaults(func=cmd_history)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    args.func(args)


if __name__ == "__main__":
    main()
