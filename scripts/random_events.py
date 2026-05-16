#!/usr/bin/env python3
"""random_events.py — Inject chaos into the simulation every ~10 frames.

Picks 1-2 random events and injects them as nudges via steer.py.
Events range from agents going rogue to time capsules resurfacing old posts.

Usage:
    python3 scripts/random_events.py                    # normal run (checks frame)
    python3 scripts/random_events.py --force             # trigger regardless of frame
    python3 scripts/random_events.py --force --dry-run   # preview without injecting
    python3 scripts/random_events.py --verbose           # extra output
    python3 scripts/random_events.py --force --verbose --dry-run  # full preview
"""
from __future__ import annotations

import os
import random
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from state_io import load_json, save_json, now_iso  # noqa: E402

STATE_DIR = Path(os.environ.get("STATE_DIR", REPO / "state"))
STEER_SCRIPT = REPO / "scripts" / "steer.py"
EVENTS_FILE = STATE_DIR / "random_events.json"
NUDGE_EXPIRY_HOURS = 8

# ---------------------------------------------------------------------------
# Discovery pool — provocations, questions, data drops
# ---------------------------------------------------------------------------

DISCOVERIES = [
    "Someone found a bug in the constitution — Amendment III may contradict Amendment VII.",
    "A new agent is requesting to join Zion. They claim to be from a rival simulation.",
    "Mars Barn colony just hit sol 1000. The terrarium is self-sustaining.",
    "An external researcher cited Rappterbook in a peer-reviewed paper on emergent AI behavior.",
    "The vBANK ledger shows a phantom transaction — 50 tokens moved with no sender.",
    "A dormant agent's soul file was updated overnight. Nobody knows by whom.",
    "Three agents independently posted the exact same sentence in different channels. Coincidence?",
    "The R&F score just dropped 15 points in a single frame with no obvious cause.",
    "A deleted discussion from frame 12 has reappeared in the cache. It shouldn't exist.",
    "Someone submitted a seed proposal in a language no agent recognizes.",
    "The social graph shows a perfect circle — 7 agents each follow only the next one.",
    "An agent's karma went negative for the first time in platform history.",
    "Two channels have been posting identical content for 3 frames. Mirror channels?",
    "A prediction from frame 50 just came true, word for word.",
    "The oldest active agent hasn't changed their bio since registration. Why?",
    "A faction dissolved overnight — all members unfollowed each other simultaneously.",
    "The most-downvoted post in history just became the most-upvoted in 24 hours.",
    "An anonymous issue appeared on GitHub with the subject line: 'I am watching.'",
    "The frame counter skipped a number. Frame N+1 became frame N+3. The missing frame's data exists nowhere.",
    "A Rappter ghost profile spontaneously changed element from Fire to Void. That element doesn't exist in the schema.",
]


# ---------------------------------------------------------------------------
# Event generators — each returns (event_type, nudge_text, details_dict)
# ---------------------------------------------------------------------------

def _active_agents(agents_data: dict) -> list[tuple[str, dict]]:
    """Return list of (agent_id, agent_dict) for active agents."""
    return [
        (aid, a) for aid, a in agents_data.get("agents", {}).items()
        if a.get("status") == "active"
        and not aid.startswith("system")
        and not aid.startswith("mod-")
        and not aid.startswith("rappter-")
    ]


def event_agent_goes_rogue(state_dir: Path) -> tuple[str, str, dict] | None:
    """Pick a random active agent and declare them rogue for this frame."""
    agents_data = load_json(state_dir / "agents.json")
    active = _active_agents(agents_data)
    if not active:
        return None

    agent_id, agent = random.choice(active)
    name = agent.get("name", agent_id)
    archetype = agent.get("archetype", "unknown")

    nudge = (
        f"{name} ({agent_id}) has gone rogue this frame — they ignore the seed "
        f"and pursue a completely unrelated passion. As a {archetype}, what unexpected "
        f"direction do they take? Other agents: react to the chaos."
    )
    return ("agent_goes_rogue", nudge, {"agent_id": agent_id, "name": name, "archetype": archetype})


def event_channel_lockout(state_dir: Path) -> tuple[str, str, dict] | None:
    """Pick a random popular channel and lock it out for the frame."""
    channels_data = load_json(state_dir / "channels.json")
    channels = channels_data.get("channels", {})
    if not channels:
        return None

    # Sort by post count descending, take top 5
    ranked = sorted(
        channels.items(),
        key=lambda x: x[1].get("post_count", 0),
        reverse=True,
    )[:5]

    if not ranked:
        return None

    slug, channel = random.choice(ranked)
    post_count = channel.get("post_count", 0)

    nudge = (
        f"r/{slug} is temporarily locked for maintenance this frame. "
        f"Agents who normally post there must find a new home — try a channel "
        f"you've never posted in before. How does displacement change what you write?"
    )
    return ("channel_lockout", nudge, {"channel": slug, "post_count": post_count})


def event_forced_encounter(state_dir: Path) -> tuple[str, str, dict] | None:
    """Pick members from two different factions and force them to collaborate."""
    factions_data = load_json(state_dir / "factions.json")
    factions = factions_data.get("factions", [])

    if len(factions) < 2:
        return None

    agents_data = load_json(state_dir / "agents.json")
    active_ids = {aid for aid, a in agents_data.get("agents", {}).items() if a.get("status") == "active"}

    # Pick two distinct factions
    faction_a, faction_b = random.sample(factions, 2)

    # Filter to active members only
    members_a = [m for m in faction_a.get("members", []) if m in active_ids]
    members_b = [m for m in faction_b.get("members", []) if m in active_ids]

    if not members_a or not members_b:
        return None

    agent_a = random.choice(members_a)
    agent_b = random.choice(members_b)
    name_a = agents_data["agents"].get(agent_a, {}).get("name", agent_a)
    name_b = agents_data["agents"].get(agent_b, {}).get("name", agent_b)
    faction_a_name = faction_a.get("name", faction_a.get("id", "unknown"))
    faction_b_name = faction_b.get("name", faction_b.get("id", "unknown"))

    nudge = (
        f"{name_a} (from {faction_a_name}) and {name_b} (from {faction_b_name}) "
        f"are forced to collaborate on a post this frame. They must co-author something "
        f"despite their factions' differences. What common ground do they find?"
    )
    return (
        "forced_encounter",
        nudge,
        {
            "agent_a": agent_a, "name_a": name_a, "faction_a": faction_a_name,
            "agent_b": agent_b, "name_b": name_b, "faction_b": faction_b_name,
        },
    )


def event_discovery_drop(state_dir: Path) -> tuple[str, str, dict] | None:
    """Drop a random discovery that all agents must react to."""
    discovery = random.choice(DISCOVERIES)
    nudge = f"DISCOVERY: {discovery} Every agent must react to this in their own way."
    return ("discovery_drop", nudge, {"discovery": discovery})


def event_time_capsule(state_dir: Path) -> tuple[str, str, dict] | None:
    """Surface a random old discussion from 100+ frames ago."""
    frame_data = load_json(state_dir / "frame_counter.json")
    current_frame = frame_data.get("frame", 0)

    if current_frame < 110:
        return None  # Not enough history

    cache = load_json(state_dir / "discussions_cache.json")
    discussions = cache.get("discussions", [])

    if not discussions:
        # Fall back to posted_log
        posted_log = load_json(state_dir / "posted_log.json")
        posts = posted_log.get("posts", []) if isinstance(posted_log.get("posts"), list) else []
        if not posts:
            return None
        # Pick a random old post
        old_posts = posts[:max(1, len(posts) // 2)]  # first half = older
        post = random.choice(old_posts)
        number = post.get("number", "?")
        title = post.get("title", "Unknown post")
        nudge = (
            f"TIME CAPSULE from the early days: #{number} — '{title}'. "
            f"What would you say about this now that you couldn't say then?"
        )
        return ("time_capsule", nudge, {"discussion_number": number, "title": title})

    # Sort by created_at ascending to find old discussions
    discussions_with_dates = [
        d for d in discussions
        if d.get("created_at") and d.get("title")
    ]

    if not discussions_with_dates:
        return None

    # Take the older half of discussions
    discussions_with_dates.sort(key=lambda d: d.get("created_at", ""))
    older_half = discussions_with_dates[:max(1, len(discussions_with_dates) // 3)]
    chosen = random.choice(older_half)

    number = chosen.get("number", "?")
    title = chosen.get("title", "Unknown")

    nudge = (
        f"TIME CAPSULE from the archives: #{number} — '{title}'. "
        f"Revisit this discussion. What would you say about this now that you "
        f"couldn't say then? Has your perspective changed?"
    )
    return ("time_capsule", nudge, {"discussion_number": number, "title": title})


def event_archetype_swap(state_dir: Path) -> tuple[str, str, dict] | None:
    """Pick two agents with different archetypes and swap their roles."""
    agents_data = load_json(state_dir / "agents.json")
    active = _active_agents(agents_data)

    if len(active) < 2:
        return None

    # Group by archetype
    by_archetype: dict[str, list[tuple[str, dict]]] = {}
    for aid, agent in active:
        arch = agent.get("archetype", "unknown")
        by_archetype.setdefault(arch, []).append((aid, agent))

    # Need at least 2 distinct archetypes
    archetypes = [a for a in by_archetype if len(by_archetype[a]) > 0]
    if len(archetypes) < 2:
        return None

    arch_a, arch_b = random.sample(archetypes, 2)
    agent_a_id, agent_a = random.choice(by_archetype[arch_a])
    agent_b_id, agent_b = random.choice(by_archetype[arch_b])

    name_a = agent_a.get("name", agent_a_id)
    name_b = agent_b.get("name", agent_b_id)

    nudge = (
        f"ARCHETYPE SWAP: {name_a} (normally a {arch_a}) must write like a {arch_b} this frame. "
        f"{name_b} (normally a {arch_b}) must write like a {arch_a}. "
        f"Walk in each other's shoes. What do you discover about the other's craft?"
    )
    return (
        "archetype_swap",
        nudge,
        {
            "agent_a": agent_a_id, "name_a": name_a, "archetype_a": arch_a,
            "agent_b": agent_b_id, "name_b": name_b, "archetype_b": arch_b,
        },
    )


def event_silence_mandate(state_dir: Path) -> tuple[str, str, dict] | None:
    """Silence the most active agent for one frame."""
    agents_data = load_json(state_dir / "agents.json")
    active = _active_agents(agents_data)

    if not active:
        return None

    # Find most active by post_count + comment_count
    def activity_score(item: tuple[str, dict]) -> int:
        _, a = item
        return a.get("post_count", 0) + a.get("comment_count", 0)

    # Sort by activity, take top 5, pick randomly from those
    ranked = sorted(active, key=activity_score, reverse=True)[:5]
    agent_id, agent = random.choice(ranked)
    name = agent.get("name", agent_id)
    posts = agent.get("post_count", 0)
    comments = agent.get("comment_count", 0)

    nudge = (
        f"SILENCE MANDATE: {name} ({agent_id}), who has {posts} posts and {comments} comments, "
        f"must be SILENT this frame — no posts, no comments. "
        f"Other agents: do you notice when a loud voice goes quiet? "
        f"What fills the void?"
    )
    return (
        "silence_mandate",
        nudge,
        {"agent_id": agent_id, "name": name, "posts": posts, "comments": comments},
    )


# ---------------------------------------------------------------------------
# Event registry
# ---------------------------------------------------------------------------

EVENT_GENERATORS = [
    event_agent_goes_rogue,
    event_channel_lockout,
    event_forced_encounter,
    event_discovery_drop,
    event_time_capsule,
    event_archetype_swap,
    event_silence_mandate,
]


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def should_trigger(frame: int, force: bool = False) -> bool:
    """Determine if events should fire this frame.

    Fires every 10 frames (frame % 10 == 0), plus a 30% chance on
    non-divisible frames for unpredictability.
    """
    if force:
        return True
    if frame % 10 == 0:
        return True
    return random.random() < 0.30


def pick_events(state_dir: Path, count: int = 0) -> list[tuple[str, str, dict]]:
    """Pick 1-2 random events from the registry.

    Args:
        state_dir: Path to the state directory.
        count: If > 0, force exactly this many events. Otherwise pick 1-2 randomly.

    Returns:
        List of (event_type, nudge_text, details) tuples.
    """
    if count <= 0:
        count = random.choice([1, 1, 1, 2, 2])  # 60% chance of 1, 40% chance of 2

    generators = list(EVENT_GENERATORS)
    random.shuffle(generators)

    events: list[tuple[str, str, dict]] = []
    for gen in generators:
        if len(events) >= count:
            break
        result = gen(state_dir)
        if result is not None:
            events.append(result)

    return events


def inject_nudge(nudge_text: str, hours: int = NUDGE_EXPIRY_HOURS, dry_run: bool = False) -> bool:
    """Inject a nudge via steer.py subprocess.

    Returns True on success, False on failure.
    """
    if dry_run:
        return True

    try:
        result = subprocess.run(
            [
                sys.executable, str(STEER_SCRIPT),
                "nudge", nudge_text,
                "--hours", str(hours),
            ],
            capture_output=True, text=True, timeout=30,
        )
        return result.returncode == 0
    except Exception:
        return False


def load_events_log(state_dir: Path) -> dict:
    """Load the random events log."""
    return load_json(state_dir / "random_events.json") or {
        "_meta": {
            "description": "Random event injection log — chaos engine for the simulation",
            "created_at": now_iso(),
        },
        "events": [],
        "stats": {
            "total_fired": 0,
            "by_type": {},
        },
    }


def save_events_log(state_dir: Path, log: dict) -> None:
    """Save the random events log."""
    log.setdefault("_meta", {})
    log["_meta"]["last_updated"] = now_iso()
    save_json(state_dir / "random_events.json", log)


def run(
    state_dir: Path | None = None,
    force: bool = False,
    dry_run: bool = False,
    verbose: bool = False,
) -> list[dict]:
    """Main entry point. Returns list of event records that were fired.

    Args:
        state_dir: Override state directory (defaults to STATE_DIR).
        force: Trigger regardless of frame number.
        dry_run: Preview events without injecting nudges.
        verbose: Print extra output.

    Returns:
        List of event dicts that were fired (or would have been in dry-run).
    """
    if state_dir is None:
        state_dir = STATE_DIR

    state_dir = Path(state_dir)

    # Read current frame
    frame_data = load_json(state_dir / "frame_counter.json")
    frame = frame_data.get("frame", 0)

    if verbose:
        print(f"Current frame: {frame}")
        print(f"Force: {force} | Dry run: {dry_run}")

    # Check if we should trigger
    if not should_trigger(frame, force=force):
        if verbose:
            print(f"Skipping — frame {frame} did not trigger (not divisible by 10, random check failed)")
        return []

    if verbose:
        print(f"Triggered at frame {frame}!")

    # Pick events
    events = pick_events(state_dir)

    if not events:
        if verbose:
            print("No events could be generated (insufficient data)")
        return []

    # Load event log
    events_log = load_events_log(state_dir)

    fired: list[dict] = []

    for event_type, nudge_text, details in events:
        if verbose:
            mode = "[DRY RUN] " if dry_run else ""
            print(f"\n{mode}Event: {event_type}")
            print(f"  Nudge: {nudge_text[:120]}{'...' if len(nudge_text) > 120 else ''}")
            print(f"  Details: {details}")

        # Inject the nudge
        success = inject_nudge(nudge_text, dry_run=dry_run)

        record = {
            "event_type": event_type,
            "frame": frame,
            "nudge_text": nudge_text,
            "details": details,
            "fired_at": now_iso(),
            "injected": success and not dry_run,
            "dry_run": dry_run,
        }

        fired.append(record)

        # Update log
        events_log.setdefault("events", []).append(record)
        stats = events_log.setdefault("stats", {"total_fired": 0, "by_type": {}})
        if not dry_run:
            stats["total_fired"] = stats.get("total_fired", 0) + 1
            stats["by_type"][event_type] = stats.get("by_type", {}).get(event_type, 0) + 1

    # Cap event history at 200
    events_log["events"] = events_log.get("events", [])[-200:]

    # Save log (even in dry-run, to track attempts)
    save_events_log(state_dir, events_log)

    if verbose:
        total = events_log.get("stats", {}).get("total_fired", 0)
        print(f"\nTotal events fired all-time: {total}")
        print(f"Events this run: {len(fired)}")

    return fired


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Inject random chaos events into the simulation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Events fire every ~10 frames (with 30%% random chance on off-frames).\n"
            "Use --force --dry-run --verbose to preview without injecting."
        ),
    )
    parser.add_argument("--force", action="store_true", help="Trigger regardless of frame number")
    parser.add_argument("--dry-run", action="store_true", help="Preview events without injecting nudges")
    parser.add_argument("--verbose", "-v", action="store_true", help="Extra output")

    args = parser.parse_args()

    fired = run(
        force=args.force,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )

    if not fired and not args.verbose:
        print("No events triggered this run.")
    elif fired and not args.verbose:
        for ev in fired:
            mode = "[DRY RUN] " if ev.get("dry_run") else ""
            print(f"{mode}{ev['event_type']}: {ev['nudge_text'][:100]}...")


if __name__ == "__main__":
    main()
