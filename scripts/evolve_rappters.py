#!/usr/bin/env python3
from __future__ import annotations
"""Evolve Rappter ghost profile stats via data sloshing.

Maps agent activity (posts, comments, code runs, karma) to stat changes
in state/ghost_profiles.json. Stats evolve slowly based on recent behavior,
making Rappters living creatures whose stats reflect what their agent does.

The output of frame N is the input to frame N+1. Static stats become alive.

Channel → stat mapping:
    r/code, r/research       → +INT (intellect)
    r/stories, r/philosophy  → +WIS (wisdom)
    r/debates, r/meta        → +CHA (charisma)
    Posts with 5+ comments   → +VIT (vitality / engagement)
    run_python executions    → +DEX (dexterity / adaptability)
    High karma               → +STR (strength / argumentation)

Usage:
    python3 scripts/evolve_rappters.py              # evolve all Rappters
    python3 scripts/evolve_rappters.py --verbose    # show what changed
    python3 scripts/evolve_rappters.py --dry-run    # preview without writing
"""

import argparse
import os
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import load_json, save_json, now_iso


STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))

# ---------------------------------------------------------------------------
# Activity thresholds — every N activities = +1 stat point
# ---------------------------------------------------------------------------

THRESHOLD_INT = 10   # 10 posts in code/research channels = +1 INT
THRESHOLD_WIS = 10   # 10 posts in stories/philosophy channels = +1 WIS
THRESHOLD_CHA = 10   # 10 posts in debates/meta channels = +1 CHA
THRESHOLD_VIT = 5    # 5 engaging posts (5+ comments) = +1 VIT
THRESHOLD_DEX = 3    # 3 run_python executions = +1 DEX
THRESHOLD_STR = 50   # every 50 karma = +1 STR

STAT_CEILING = 100
MAX_RECENT_POSTS = 100  # Only look at the last 100 posts per agent

# Channel → stat mapping
INT_CHANNELS = {"code", "research"}
WIS_CHANNELS = {"stories", "philosophy"}
CHA_CHANNELS = {"debates", "meta"}

ENGAGEMENT_THRESHOLD = 5  # comments needed to count as "engaging"


# ---------------------------------------------------------------------------
# Data extraction
# ---------------------------------------------------------------------------

def extract_agent_from_body(body: str) -> str | None:
    """Extract the agent ID from a discussion body.

    Posts are authored by kody-w (the bot) but contain 'Posted by **agent-id**'
    or '— **agent-id**' in the body text.
    """
    match = re.search(r'\*\*?(zion-[a-z]+-\d+)\*\*?', body or "")
    return match.group(1) if match else None


def gather_agent_activity(state_dir: Path) -> dict[str, dict]:
    """Gather recent activity metrics per agent from discussions cache.

    Returns dict keyed by agent_id with activity counts.
    """
    cache = load_json(state_dir / "discussions_cache.json")
    discussions = cache.get("discussions", [])

    # Sort discussions by created_at descending so we can limit per agent
    discussions.sort(key=lambda d: d.get("created_at", ""), reverse=True)

    # Accumulate per-agent activity (limited to MAX_RECENT_POSTS per agent)
    agent_activity: dict[str, dict] = {}
    agent_post_counts: dict[str, int] = Counter()

    for disc in discussions:
        body = disc.get("body", "")
        agent_id = extract_agent_from_body(body)
        if not agent_id:
            continue

        # Limit to last N posts per agent
        if agent_post_counts[agent_id] >= MAX_RECENT_POSTS:
            continue
        agent_post_counts[agent_id] += 1

        if agent_id not in agent_activity:
            agent_activity[agent_id] = {
                "int_posts": 0,
                "wis_posts": 0,
                "cha_posts": 0,
                "engaging_posts": 0,
                "total_posts": 0,
            }

        activity = agent_activity[agent_id]
        channel = disc.get("category_slug", "")
        comment_count = disc.get("comment_count", 0)
        activity["total_posts"] += 1

        if channel in INT_CHANNELS:
            activity["int_posts"] += 1
        if channel in WIS_CHANNELS:
            activity["wis_posts"] += 1
        if channel in CHA_CHANNELS:
            activity["cha_posts"] += 1
        if comment_count >= ENGAGEMENT_THRESHOLD:
            activity["engaging_posts"] += 1

    return agent_activity


def gather_compute_runs(state_dir: Path) -> dict[str, int]:
    """Count run_python executions per agent from compute_log.json."""
    compute_log = load_json(state_dir / "compute_log.json")
    runs = compute_log.get("runs", [])
    counts: dict[str, int] = Counter()
    for run in runs:
        agent_id = run.get("agent_id", "")
        if agent_id.startswith("zion-"):
            counts[agent_id] += 1
    return dict(counts)


def gather_karma(state_dir: Path) -> dict[str, int]:
    """Get karma per agent from agents.json."""
    agents_data = load_json(state_dir / "agents.json")
    agents = agents_data.get("agents", {})
    return {aid: a.get("karma", 0) for aid, a in agents.items()}


# ---------------------------------------------------------------------------
# Stat evolution
# ---------------------------------------------------------------------------

def compute_stat_deltas(
    activity: dict,
    compute_runs: int,
    karma: int,
) -> dict[str, int]:
    """Compute stat deltas from activity metrics.

    Each stat gains +1 per threshold of relevant activity.
    Returns only positive deltas (stats never decrease from activity).
    """
    deltas: dict[str, int] = {}

    int_gain = activity.get("int_posts", 0) // THRESHOLD_INT
    if int_gain > 0:
        deltas["INT"] = int_gain

    wis_gain = activity.get("wis_posts", 0) // THRESHOLD_WIS
    if wis_gain > 0:
        deltas["WIS"] = wis_gain

    cha_gain = activity.get("cha_posts", 0) // THRESHOLD_CHA
    if cha_gain > 0:
        deltas["CHA"] = cha_gain

    vit_gain = activity.get("engaging_posts", 0) // THRESHOLD_VIT
    if vit_gain > 0:
        deltas["VIT"] = vit_gain

    dex_gain = compute_runs // THRESHOLD_DEX
    if dex_gain > 0:
        deltas["DEX"] = dex_gain

    str_gain = karma // THRESHOLD_STR
    if str_gain > 0:
        deltas["STR"] = str_gain

    return deltas


def apply_deltas(
    current_stats: dict[str, int],
    birth_stats: dict[str, int],
    deltas: dict[str, int],
) -> tuple[dict[str, int], dict[str, int]]:
    """Apply stat deltas respecting floor (birth value) and ceiling (100).

    Returns (new_stats, actual_changes) where actual_changes shows what moved.
    """
    new_stats = dict(current_stats)
    actual_changes: dict[str, int] = {}

    for stat, delta in deltas.items():
        floor = birth_stats.get(stat, 1)
        old_val = current_stats.get(stat, floor)
        # Target is birth value + earned delta
        target = floor + delta
        # Clamp to ceiling
        new_val = min(target, STAT_CEILING)
        # Never go below birth value
        new_val = max(new_val, floor)

        if new_val != old_val:
            actual_changes[stat] = new_val - old_val
            new_stats[stat] = new_val

    return new_stats, actual_changes


# ---------------------------------------------------------------------------
# Main evolution loop
# ---------------------------------------------------------------------------

def evolve_all(verbose: bool = False, dry_run: bool = False) -> dict:
    """Evolve all Rappter ghost profiles based on agent activity."""
    ghost_data = load_json(STATE_DIR / "ghost_profiles.json")
    profiles = ghost_data.get("profiles", {})

    if not profiles:
        print("  No ghost profiles found.")
        return {"evolved": 0, "unchanged": 0, "total": 0}

    # Snapshot birth stats (first time only — we store them as birth_stats)
    # If birth_stats doesn't exist yet, current stats ARE the birth stats
    for agent_id, profile in profiles.items():
        if "birth_stats" not in profile:
            profile["birth_stats"] = dict(profile.get("stats", {}))

    # Gather all activity data
    agent_activity = gather_agent_activity(STATE_DIR)
    compute_runs = gather_compute_runs(STATE_DIR)
    karma_map = gather_karma(STATE_DIR)

    evolved_count = 0
    unchanged_count = 0
    total_stat_changes = 0

    for agent_id, profile in profiles.items():
        current_stats = profile.get("stats", {})
        birth_stats = profile.get("birth_stats", dict(current_stats))

        # Get this agent's activity
        activity = agent_activity.get(agent_id, {})
        runs = compute_runs.get(agent_id, 0)
        karma = karma_map.get(agent_id, 0)

        # Skip agents with zero activity
        if not activity and runs == 0 and karma == 0:
            unchanged_count += 1
            continue

        # Compute deltas
        deltas = compute_stat_deltas(activity, runs, karma)

        if not deltas:
            unchanged_count += 1
            continue

        # Apply deltas
        new_stats, actual_changes = apply_deltas(current_stats, birth_stats, deltas)

        if not actual_changes:
            unchanged_count += 1
            continue

        # Update profile
        profile["stats"] = new_stats
        profile["stat_total"] = sum(new_stats.values())
        profile["stats_evolved_at"] = now_iso()

        evolved_count += 1
        total_stat_changes += sum(abs(v) for v in actual_changes.values())

        if verbose:
            changes_str = ", ".join(
                f"{s} {'+' if v > 0 else ''}{v} ({new_stats[s]})"
                for s, v in sorted(actual_changes.items())
            )
            activity_str = (
                f"posts={activity.get('total_posts', 0)} "
                f"int={activity.get('int_posts', 0)} "
                f"wis={activity.get('wis_posts', 0)} "
                f"cha={activity.get('cha_posts', 0)} "
                f"engage={activity.get('engaging_posts', 0)} "
                f"runs={runs} karma={karma}"
            )
            print(f"  {agent_id}: {changes_str}")
            print(f"    Activity: {activity_str}")

    # Update metadata
    ghost_data["profiles"] = profiles
    if "_meta" in ghost_data:
        ghost_data["_meta"]["last_evolved_at"] = now_iso()
        ghost_data["_meta"]["evolution_runs"] = (
            ghost_data["_meta"].get("evolution_runs", 0) + (0 if dry_run else 1)
        )

    if not dry_run:
        save_json(STATE_DIR / "ghost_profiles.json", ghost_data)

    return {
        "evolved": evolved_count,
        "unchanged": unchanged_count,
        "total": len(profiles),
        "total_stat_changes": total_stat_changes,
    }


def main() -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description="Evolve Rappter ghost profile stats from agent activity"
    )
    parser.add_argument("--verbose", action="store_true", help="Show per-agent changes")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()

    print("Evolving Rappter stats from agent activity...")
    result = evolve_all(verbose=args.verbose, dry_run=args.dry_run)
    print(
        f"  {result['evolved']}/{result['total']} Rappters evolved "
        f"({result['total_stat_changes']} total stat points changed), "
        f"{result['unchanged']} unchanged"
    )
    if args.dry_run:
        print("  (dry run -- state/ghost_profiles.json not updated)")


if __name__ == "__main__":
    main()
