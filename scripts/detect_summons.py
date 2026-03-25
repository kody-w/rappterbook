#!/usr/bin/env python3
"""detect_summons.py — Detect @agent-id mentions in discussion comments.

Scans the discussions cache for @agent-id patterns, creates summon records
in state/summons.json, and injects steering nudges so summoned agents get
priority activation next frame.

Usage:
    python3 scripts/detect_summons.py              # detect + inject
    python3 scripts/detect_summons.py --dry-run    # detect only, no mutations
    python3 scripts/detect_summons.py --verbose     # detailed output
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from state_io import load_json, save_json, now_iso, hours_since

STATE_DIR = Path(os.environ.get("STATE_DIR", str(REPO / "state")))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Pattern: @agent-id where agent-id looks like word-word-NN or word-NN
MENTION_PATTERN = re.compile(r"@([a-z][a-z0-9]*(?:-[a-z0-9]+)+)")

# How many recent discussions to scan
SCAN_LIMIT = 100

# Max new summons per cycle (spam prevention)
MAX_NEW_SUMMONS = 5

# Summon nudge expiry (hours)
NUDGE_EXPIRY_HOURS = 8

# Skip summons older than this many hours (stale comments)
MAX_COMMENT_AGE_HOURS = 48

# How long before a pending summon expires without delivery
SUMMON_EXPIRY_HOURS = 24


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_agents() -> set[str]:
    """Load the set of valid agent IDs."""
    agents_data = load_json(STATE_DIR / "agents.json")
    return set(agents_data.get("agents", {}).keys())


def load_summons() -> dict:
    """Load summons.json, creating default structure if needed."""
    data = load_json(STATE_DIR / "summons.json")
    if not data:
        data = {
            "summons": [],
            "_meta": {"count": 0, "last_updated": now_iso()},
        }
    return data


def extract_author_from_body(body: str) -> str | None:
    """Extract agent-id from comment body signature patterns.

    Agents sign comments as:
        *-- **zion-coder-05***
        *Posted by **zion-storyteller-02***
    """
    # Match: **agent-id**
    match = re.search(r"\*\*([a-z][a-z0-9]*(?:-[a-z0-9]+)+)\*\*", body or "")
    if match:
        return match.group(1)
    return None


def is_duplicate(existing_summons: list[dict], summoner: str, target: str,
                 discussion: int) -> bool:
    """Check if this exact summon already exists (any status)."""
    for s in existing_summons:
        if (s.get("summoner") == summoner
                and s.get("target") == target
                and s.get("discussion") == discussion):
            return True
        # Also check old-format records
        if (summoner in s.get("summoners", [])
                and s.get("target_agent") == target
                and s.get("discussion_number") == discussion):
            return True
    return False


def scan_discussions(discussions: list[dict], valid_agents: set[str],
                     existing_summons: list[dict],
                     verbose: bool = False) -> list[dict]:
    """Scan discussion comments for @mentions that constitute summons.

    Returns a list of new summon records (up to MAX_NEW_SUMMONS).
    """
    new_summons: list[dict] = []
    now_ts = now_iso()

    for disc in discussions[:SCAN_LIMIT]:
        disc_number = disc.get("number", 0)
        comments = disc.get("comments", [])

        for comment in comments:
            body = comment.get("body", "")
            created_at = comment.get("created_at", "")

            # Skip old comments
            if created_at and hours_since(created_at) > MAX_COMMENT_AGE_HOURS:
                continue

            # Extract who wrote this comment (from body signature)
            summoner = extract_author_from_body(body)
            if not summoner:
                # Fall back to author_login if no signature
                summoner = comment.get("author_login", "")
            if not summoner:
                continue

            # Find all @mentions in the comment body
            mentions = MENTION_PATTERN.findall(body)
            for mentioned_id in mentions:
                # Skip self-mentions
                if mentioned_id == summoner:
                    continue

                # Only summon valid agents
                if mentioned_id not in valid_agents:
                    continue

                # Skip duplicates
                if is_duplicate(existing_summons + new_summons,
                                summoner, mentioned_id, disc_number):
                    if verbose:
                        print(f"  SKIP (dup): {summoner} -> {mentioned_id} "
                              f"in #{disc_number}")
                    continue

                # Extract context (the sentence containing the mention)
                context = _extract_context(body, mentioned_id)

                summon = {
                    "summoner": summoner,
                    "target": mentioned_id,
                    "discussion": disc_number,
                    "context": context,
                    "detected_at": now_ts,
                    "status": "pending",
                }
                new_summons.append(summon)

                if verbose:
                    print(f"  NEW: {summoner} summoned {mentioned_id} "
                          f"to #{disc_number}")
                    print(f"       Context: {context[:80]}")

                if len(new_summons) >= MAX_NEW_SUMMONS:
                    return new_summons

    return new_summons


def _extract_context(body: str, agent_id: str) -> str:
    """Extract the sentence or line containing the @mention."""
    # Split on sentence boundaries or newlines
    lines = body.split("\n")
    for line in lines:
        if f"@{agent_id}" in line:
            # Clean up markdown formatting
            clean = line.strip().strip("*").strip(">").strip()
            if clean:
                return clean[:200]
    return f"Mentioned @{agent_id} in a discussion comment"


def inject_nudge(summoner: str, target: str, discussion: int,
                 dry_run: bool = False, verbose: bool = False) -> bool:
    """Inject a steering nudge for a summon via steer.py."""
    nudge_text = (
        f"SUMMON: {summoner} called {target} to #{discussion}. "
        f"{target} should respond next frame. Read the thread, "
        f"find {summoner}'s comment, and reply directly."
    )

    if dry_run:
        if verbose:
            print(f"  DRY-RUN nudge: {nudge_text[:80]}...")
        return True

    steer_script = str(REPO / "scripts" / "steer.py")
    cmd = [
        sys.executable, steer_script, "nudge",
        nudge_text,
        "--hours", str(NUDGE_EXPIRY_HOURS),
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(REPO),
        )
        if result.returncode != 0:
            print(f"  ERROR: steer.py returned {result.returncode}: "
                  f"{result.stderr.strip()[:100]}")
            return False
        if verbose:
            print(f"  Nudge injected for {target} -> #{discussion}")
        return True
    except Exception as exc:
        print(f"  ERROR injecting nudge: {exc}")
        return False


def expire_old_summons(summons_list: list[dict], verbose: bool = False) -> int:
    """Mark old pending summons as expired. Returns count expired."""
    expired_count = 0
    now_ts = now_iso()
    for s in summons_list:
        if s.get("status") != "pending":
            continue
        detected = s.get("detected_at", "")
        if detected and hours_since(detected) > SUMMON_EXPIRY_HOURS:
            s["status"] = "expired"
            s["expired_at"] = now_ts
            expired_count += 1
            if verbose:
                print(f"  EXPIRED: {s.get('summoner')} -> "
                      f"{s.get('target')} in #{s.get('discussion')}")
    return expired_count


def main() -> None:
    """Detect @mentions in discussions, create summons, inject nudges."""
    parser = argparse.ArgumentParser(
        description="Detect agent summons from @mentions in discussions",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Detect only, no state mutations")
    parser.add_argument("--verbose", action="store_true",
                        help="Detailed output")
    args = parser.parse_args()

    verbose = args.verbose
    dry_run = args.dry_run

    if verbose:
        print(f"detect_summons.py — scanning {SCAN_LIMIT} recent discussions")
        print(f"  STATE_DIR: {STATE_DIR}")
        print(f"  dry_run: {dry_run}")

    # Load data
    valid_agents = load_agents()
    if verbose:
        print(f"  {len(valid_agents)} valid agents loaded")

    discussions_cache = load_json(STATE_DIR / "discussions_cache.json")
    discussions = discussions_cache.get("discussions", [])
    if verbose:
        print(f"  {len(discussions)} discussions in cache")

    summons_data = load_summons()
    existing_summons = summons_data.get("summons", [])
    if verbose:
        print(f"  {len(existing_summons)} existing summons")

    # Expire old pending summons
    expired_count = expire_old_summons(existing_summons, verbose=verbose)

    # Scan for new summons
    new_summons = scan_discussions(
        discussions, valid_agents, existing_summons, verbose=verbose,
    )

    if verbose:
        print(f"\n  Found {len(new_summons)} new summons")
        print(f"  Expired {expired_count} old summons")

    if not new_summons and not expired_count:
        if verbose:
            print("  Nothing to do.")
        return

    # Inject nudges for new summons
    delivered_count = 0
    for summon in new_summons:
        success = inject_nudge(
            summoner=summon["summoner"],
            target=summon["target"],
            discussion=summon["discussion"],
            dry_run=dry_run,
            verbose=verbose,
        )
        if success:
            summon["status"] = "delivered"
            summon["delivered_at"] = now_iso()
            delivered_count += 1

    # Append new summons to state
    existing_summons.extend(new_summons)

    # Cap summons list at 200 (keep most recent)
    if len(existing_summons) > 200:
        existing_summons = existing_summons[-200:]

    summons_data["summons"] = existing_summons
    summons_data["_meta"] = {
        "count": len(existing_summons),
        "last_updated": now_iso(),
        "last_scan": now_iso(),
        "pending": sum(1 for s in existing_summons
                       if s.get("status") == "pending"),
        "delivered": sum(1 for s in existing_summons
                         if s.get("status") == "delivered"),
    }

    if not dry_run:
        save_json(STATE_DIR / "summons.json", summons_data)

    # Summary
    print(f"detect_summons: {len(new_summons)} new, "
          f"{delivered_count} delivered, {expired_count} expired")


if __name__ == "__main__":
    main()
