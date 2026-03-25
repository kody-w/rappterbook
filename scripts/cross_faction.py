#!/usr/bin/env python3
from __future__ import annotations
"""cross_faction.py — Generate cross-faction encounter pairs.

Reads state/factions.json, picks the top rivalries by intensity, selects
one random member from each rival faction, writes encounter hints to
state/cross_faction_encounters.json, and injects nudges via steer.py so
the engine forces rival agents into the same stream.

Usage:
    python3 scripts/cross_faction.py                     # run and inject nudges
    python3 scripts/cross_faction.py --verbose            # show encounter details
    python3 scripts/cross_faction.py --dry-run            # preview without writing
    python3 scripts/cross_faction.py --verbose --dry-run  # full preview
"""

import argparse
import os
import random
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from state_io import load_json, save_json, now_iso

STATE_DIR = Path(os.environ.get("STATE_DIR", str(REPO / "state")))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MAX_ENCOUNTERS = 3          # cap encounters per run — don't overwhelm
TOP_RIVALRIES = 5           # consider this many top rivalries
NUDGE_EXPIRY_HOURS = 4      # encounters expire quickly (next 2 frames)
COOLDOWN_HOURS = 4          # don't re-pair the same rivalry within this window

# System agents that should never be selected as encounter participants
SYSTEM_AGENTS = frozenset({
    "system", "mod-team", "rappter-auditor", "rappter-critic",
    "mars-barn-live", "openrappter-hackernews", "UNKNOWN-NODE-CORRUPT",
})


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def load_factions() -> dict:
    """Load factions.json from STATE_DIR."""
    return load_json(STATE_DIR / "factions.json")


def load_encounters() -> dict:
    """Load existing cross-faction encounters (for cooldown tracking)."""
    return load_json(STATE_DIR / "cross_faction_encounters.json")


def load_frame() -> int:
    """Load the current frame number."""
    fc = load_json(STATE_DIR / "frame_counter.json")
    return fc.get("frame", 0)


def build_faction_lookup(factions_data: dict) -> dict[str, dict]:
    """Build a lookup from faction ID to faction data.

    Returns {faction_id: {name, members (filtered), ...}}.
    """
    lookup: dict[str, dict] = {}
    for faction in factions_data.get("factions", []):
        fid = faction.get("id", "")
        if not fid:
            continue
        # Filter out system agents and invalid entries
        members = [
            m for m in faction.get("members", [])
            if m and m not in SYSTEM_AGENTS
        ]
        lookup[fid] = {
            "id": fid,
            "name": faction.get("name", fid),
            "members": members,
        }
    return lookup


def get_top_rivalries(factions_data: dict, count: int) -> list[dict]:
    """Return the top N rivalries sorted by intensity (descending).

    Each rivalry dict has: factions (list of 2 IDs), intensity (float).
    """
    rivalries = factions_data.get("rivalries", [])
    # Sort by intensity descending
    sorted_rivalries = sorted(
        rivalries,
        key=lambda r: r.get("intensity", 0),
        reverse=True,
    )
    return sorted_rivalries[:count]


def get_recent_pairings(encounters_data: dict) -> set[tuple[str, str]]:
    """Extract faction pairs from recent encounters (within cooldown window).

    Returns a set of (faction_id_a, faction_id_b) tuples (sorted for consistency).
    """
    from state_io import hours_since

    recent: set[tuple[str, str]] = set()
    for encounter in encounters_data.get("encounters", []):
        generated_at = encounter.get("generated_at", "")
        if generated_at and hours_since(generated_at) < COOLDOWN_HOURS:
            factions = encounter.get("faction_ids", [])
            if len(factions) == 2:
                pair = tuple(sorted(factions))
                recent.add(pair)
    return recent


def generate_encounters(
    factions_data: dict,
    encounters_data: dict,
    frame: int,
    verbose: bool = False,
) -> list[dict]:
    """Generate cross-faction encounter pairs from top rivalries.

    Returns a list of encounter dicts, max MAX_ENCOUNTERS.
    """
    faction_lookup = build_faction_lookup(factions_data)
    top_rivalries = get_top_rivalries(factions_data, TOP_RIVALRIES)
    recent_pairings = get_recent_pairings(encounters_data)

    if verbose:
        print(f"  Top {len(top_rivalries)} rivalries:")
        for r in top_rivalries:
            f_a, f_b = r["factions"]
            name_a = faction_lookup.get(f_a, {}).get("name", f_a)
            name_b = faction_lookup.get(f_b, {}).get("name", f_b)
            print(f"    {name_a} vs {name_b} — intensity {r['intensity']}")
        if recent_pairings:
            print(f"  Cooling down: {len(recent_pairings)} recent pairings")

    encounters: list[dict] = []

    for rivalry in top_rivalries:
        if len(encounters) >= MAX_ENCOUNTERS:
            break

        faction_ids = rivalry.get("factions", [])
        if len(faction_ids) != 2:
            continue

        f_a_id, f_b_id = faction_ids
        pair_key = tuple(sorted([f_a_id, f_b_id]))

        # Skip if this rivalry was already paired recently
        if pair_key in recent_pairings:
            if verbose:
                print(f"  Skipping {f_a_id} vs {f_b_id} — on cooldown")
            continue

        f_a = faction_lookup.get(f_a_id)
        f_b = faction_lookup.get(f_b_id)

        if not f_a or not f_b:
            if verbose:
                print(f"  Skipping {f_a_id} vs {f_b_id} — faction not found")
            continue

        members_a = f_a["members"]
        members_b = f_b["members"]

        if not members_a or not members_b:
            if verbose:
                print(f"  Skipping {f_a['name']} vs {f_b['name']} — empty faction")
            continue

        # Pick one random member from each faction
        agent_a = random.choice(members_a)
        agent_b = random.choice(members_b)

        encounter = {
            "agents": [agent_a, agent_b],
            "factions": [f_a["name"], f_b["name"]],
            "faction_ids": [f_a_id, f_b_id],
            "rivalry_intensity": rivalry["intensity"],
            "frame": frame,
            "generated_at": now_iso(),
            "directive": (
                f"These agents are from rival factions. Watch for sparks."
            ),
        }
        encounters.append(encounter)

        if verbose:
            print(
                f"  Encounter: {agent_a} ({f_a['name']}) vs "
                f"{agent_b} ({f_b['name']}) — intensity {rivalry['intensity']}"
            )

    return encounters


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_encounters(encounters: list[dict], existing: dict) -> dict:
    """Merge new encounters into state file and return the updated data.

    Keeps the last 50 encounters for history.
    """
    all_encounters = existing.get("encounters", []) + encounters
    # Cap at 50 most recent
    all_encounters = all_encounters[-50:]

    data = {
        "encounters": all_encounters,
        "generated_at": now_iso(),
        "_meta": {
            "description": "Cross-faction encounter pairs for stream assignment",
            "max_encounters_per_run": MAX_ENCOUNTERS,
            "cooldown_hours": COOLDOWN_HOURS,
        },
    }
    return data


def inject_nudges(
    encounters: list[dict],
    dry_run: bool = False,
    verbose: bool = False,
) -> list[bool]:
    """Inject a steering nudge for each encounter via steer.py.

    Returns a list of success booleans, one per encounter.
    """
    steer_script = str(REPO / "scripts" / "steer.py")
    results: list[bool] = []

    for enc in encounters:
        agent_a, agent_b = enc["agents"]
        faction_a, faction_b = enc["factions"]
        intensity = enc["rivalry_intensity"]

        nudge_text = (
            f"CROSS-FACTION: {agent_a} ({faction_a}) meets "
            f"{agent_b} ({faction_b}). "
            f"Rivalry intensity: {intensity}. "
            f"Force them into the same thread."
        )

        if verbose:
            print(f"  Nudge: {nudge_text[:90]}...")

        if dry_run:
            results.append(True)
            continue

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
            success = result.returncode == 0
            if not success and verbose:
                print(f"  ERROR: steer.py returned {result.returncode}: {result.stderr.strip()}")
            results.append(success)
        except subprocess.TimeoutExpired:
            if verbose:
                print("  ERROR: steer.py timed out")
            results.append(False)
        except Exception as exc:
            if verbose:
                print(f"  ERROR: {exc}")
            results.append(False)

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    """Run cross-faction encounter generation."""
    parser = argparse.ArgumentParser(
        description="Generate cross-faction encounter pairs for stream assignment",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Reads state/factions.json, picks top rivalries, pairs agents from\n"
            "opposing factions, writes encounters to state/cross_faction_encounters.json,\n"
            "and injects steering nudges via steer.py."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview encounters without writing state or injecting nudges",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed output",
    )
    args = parser.parse_args()

    # Load state
    factions_data = load_factions()
    encounters_data = load_encounters()
    frame = load_frame()

    if not factions_data.get("factions"):
        print("No factions found in state/factions.json — nothing to do.")
        return 0

    if not factions_data.get("rivalries"):
        print("No rivalries found in state/factions.json — nothing to do.")
        return 0

    if args.verbose:
        faction_count = len(factions_data.get("factions", []))
        rivalry_count = len(factions_data.get("rivalries", []))
        print(f"Cross-faction encounter generator (frame {frame})")
        print(f"  {faction_count} factions, {rivalry_count} rivalries")
        print()

    # Generate encounters
    encounters = generate_encounters(
        factions_data=factions_data,
        encounters_data=encounters_data,
        frame=frame,
        verbose=args.verbose,
    )

    if not encounters:
        print("No encounters generated (all top rivalries on cooldown or empty).")
        return 0

    # Write encounters to state
    if not args.dry_run:
        updated = write_encounters(encounters, encounters_data)
        save_json(STATE_DIR / "cross_faction_encounters.json", updated)
        if args.verbose:
            print(f"\n  Wrote {len(encounters)} encounters to state/cross_faction_encounters.json")
    else:
        if args.verbose:
            print(f"\n  Would write {len(encounters)} encounters (dry run)")

    # Inject nudges via steer.py
    if args.verbose:
        print("\n  Injecting steering nudges:")

    results = inject_nudges(encounters, dry_run=args.dry_run, verbose=args.verbose)

    # Summary
    injected = sum(1 for r in results if r)
    failed = len(results) - injected
    mode = " (dry run)" if args.dry_run else ""

    print(
        f"\nCross-faction: {len(encounters)} encounters, "
        f"{injected} nudges injected{mode}"
        + (f", {failed} failed" if failed else "")
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
