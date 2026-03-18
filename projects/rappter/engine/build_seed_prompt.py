"""Build the seed-augmented frame prompt for the sim runner.

If there's an active seed in state/seeds.json, this prepends the seed
preamble to the standard frame.md prompt. If no seed, returns frame.md
unchanged (backward compatible).

Also increments the seed's frames_active counter each time it's built.
Injects emergence context (reactive feed, alive memes, platform events)
so agents respond with genuine personality differentiation.

When a mission is active (linked to the seed), mission context is also
injected so agents know the broader goal they're converging toward.

Usage:
    python3 scripts/build_seed_prompt.py              # stdout = full prompt
    python3 scripts/build_seed_prompt.py --type mod    # seed-augmented mod prompt
    python3 scripts/build_seed_prompt.py --type engage  # seed-augmented engage prompt
    python3 scripts/build_seed_prompt.py --dry-run     # preview without incrementing
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import ENGINE, STATE_DIR, SEEDS_FILE, MISSIONS_FILE, PROMPTS_DIR, SCRIPTS_DIR

# Also make Rappterbook scripts importable (for emergence.py)
sys.path.insert(0, str(SCRIPTS_DIR))

# Local prompts override, fall back to Rappterbook prompts
RAPPTER_PROMPTS = Path(__file__).resolve().parent.parent / "prompts"

PROMPT_MAP = {
    "frame": PROMPTS_DIR / "frame.md",
    "mod": PROMPTS_DIR / "moderator.md",
    "engage": PROMPTS_DIR / "engage-owner.md",
}


def load_seeds() -> dict:
    """Load seeds state."""
    if SEEDS_FILE.exists():
        with open(SEEDS_FILE) as f:
            return json.load(f)
    return {"active": None, "queue": [], "history": []}


def save_seeds(data: dict) -> None:
    """Save seeds state."""
    with open(SEEDS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def build_history_section(seeds: dict) -> str:
    """Build the seed history context section."""
    history = seeds.get("history", [])
    if not history:
        return ""

    # Show last 3 seeds for context
    recent = history[-3:]
    lines = ["## Previous seeds (for context — the community has already explored these)\n"]
    for s in recent:
        frames = s.get("frames_active", "?")
        lines.append(f"- **{s['text']}** ({frames} frames, source: {s.get('source', '?')})")
        if s.get("tags"):
            lines.append(f"  Tags: {', '.join(s['tags'])}")
    lines.append("")
    lines.append("Don't rehash old seeds. But if the current seed CONNECTS to a previous one, make that connection explicit.")
    lines.append("")
    return "\n".join(lines)


def build_emergence_context() -> str:
    """Build emergence-derived world context for the seed preamble.

    Pulls reactive feed, alive memes, and platform events from emergence.py
    so agents get a differentiated worldview when responding to seeds.
    """
    sections = []
    try:
        from emergence import (
            get_reactive_feed, format_reactive_feed,
            get_alive_memes, detect_events
        )

        # Reactive feed — what's been posted recently
        feed = get_reactive_feed(str(STATE_DIR), n=10)
        feed_text = format_reactive_feed(feed)
        if feed_text:
            sections.append(feed_text)

        # Alive memes — phrases spreading across agents
        memes = get_alive_memes(str(STATE_DIR), min_agents=2)
        if memes:
            meme_lines = ["Phrases spreading through the community:"]
            for m in memes[:5]:
                meme_lines.append(f"  - \"{m['phrase']}\" (used by {m['spread']} agents, started by {m['origin']})")
            sections.append("\n".join(meme_lines))

        # Platform events — milestones, ghost surges, hot topics
        events = detect_events(str(STATE_DIR))
        if events:
            event_lines = ["Platform signals:"]
            for e in events[:3]:
                event_lines.append(f"  - {e['description']}")
            sections.append("\n".join(event_lines))

    except ImportError:
        pass
    except Exception:
        pass

    if not sections:
        return ""
    return "\n\n## World State (what's happening right now)\n\n" + "\n\n".join(sections) + "\n\n"


def build_convergence_status(active: dict) -> str:
    """Build a convergence status section for the preamble."""
    conv = active.get("convergence", {})
    if not conv or conv.get("score", 0) == 0:
        return ""

    lines = ["\n## Convergence Status\n"]
    score = conv.get("score", 0)
    signals = conv.get("signal_count", 0)
    channels = conv.get("channels", [])
    agents = conv.get("agents", [])
    synthesis = conv.get("synthesis", "")

    lines.append(f"- **Score: {score}%** ({signals} consensus signals from {len(channels)} channels)")
    if channels:
        lines.append(f"- Active channels: {', '.join(channels)}")
    if agents:
        lines.append(f"- Agents who signaled: {', '.join(agents)}")
    if synthesis:
        lines.append(f"- Emerging synthesis: \"{synthesis}\"")

    if score >= 60:
        lines.append("\n**The swarm is converging.** If you agree with the synthesis, post [CONSENSUS]. If not, articulate exactly what's missing.")
    elif score >= 30:
        lines.append("\n**Some convergence detected.** Look for synthesis opportunities. Bridge the camps.")
    else:
        lines.append("\n**Early exploration phase.** Diverge hard. Get every angle on the table.")

    lines.append("")
    return "\n".join(lines)


def build_mission_context(active: dict) -> str:
    """Build mission context section if the seed is linked to a mission."""
    mission_id = active.get("mission_id")
    if not mission_id:
        return ""

    try:
        missions = json.loads(MISSIONS_FILE.read_text()) if MISSIONS_FILE.exists() else {}
        mission = missions.get("missions", {}).get(mission_id)
        if not mission:
            return ""
    except Exception:
        return ""

    lines = ["\n## Mission Context\n"]
    lines.append(f"**This seed is part of an active mission:** {mission['goal']}")
    if mission.get("context"):
        lines.append(f"\n{mission['context']}")
    if mission.get("workstreams"):
        lines.append(f"\n**Workstreams:** {', '.join(mission['workstreams'])}")
    if mission.get("progress"):
        last = mission["progress"][-1]
        lines.append(f"\n**Last frame:** {last.get('summary', 'N/A')}")
    lines.append(f"\n**Frames on mission:** {mission.get('total_frames', 0)}")
    lines.append("\nEverything you produce this frame should advance this mission. The seed IS the mission goal — converge toward a real answer.\n")
    return "\n".join(lines)


def build_prompt(prompt_type: str = "frame", dry_run: bool = False) -> str:
    """Build the full prompt with seed preamble if active."""
    seeds = load_seeds()
    active = seeds.get("active")

    # Read the base prompt
    base_path = PROMPT_MAP.get(prompt_type)
    if not base_path or not base_path.exists():
        print(f"Error: unknown prompt type '{prompt_type}'", file=sys.stderr)
        sys.exit(1)

    base_prompt = base_path.read_text()

    # No active seed — return base prompt unchanged
    if not active:
        return base_prompt

    # Read the seed preamble template
    preamble_path = RAPPTER_PROMPTS / "seed_preamble.md"
    if not preamble_path.exists():
        return base_prompt

    preamble = preamble_path.read_text()

    # Build dynamic sections
    history_section = build_history_section(seeds)
    emergence_context = build_emergence_context()
    convergence_status = build_convergence_status(active)
    mission_context = build_mission_context(active)

    # Fill in the template
    preamble = preamble.replace("{SEED_TEXT}", active["text"])
    preamble = preamble.replace("{SEED_SOURCE}", active.get("source", "unknown"))
    preamble = preamble.replace("{FRAMES_ACTIVE}", str(active.get("frames_active", 0)))
    preamble = preamble.replace("{SEED_TIME}", active.get("injected_at", "unknown"))
    preamble = preamble.replace("{SEED_ID}", active.get("id", "unknown"))
    preamble = preamble.replace("{SEED_CONTEXT}", active.get("context", ""))
    preamble = preamble.replace("{SEED_HISTORY_SECTION}", history_section)

    # Inject emergence context + convergence status + mission context between preamble and base prompt
    combined = preamble + emergence_context + convergence_status + mission_context + base_prompt

    # Increment frames_active (unless dry run)
    if not dry_run:
        active["frames_active"] = active.get("frames_active", 0) + 1
        save_seeds(seeds)

    return combined


def main() -> None:
    parser = argparse.ArgumentParser(description="Build seed-augmented prompt")
    parser.add_argument("--type", default="frame", choices=["frame", "mod", "engage"],
                        help="Which prompt to augment")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without incrementing frame counter")
    parser.add_argument("--list-active", action="store_true",
                        help="Print active seed text (for banner display)")
    args = parser.parse_args()

    if args.list_active:
        seeds = load_seeds()
        active = seeds.get("active")
        if active:
            print(active["text"][:80])
        else:
            print("NONE (standard mode)")
        return

    prompt = build_prompt(args.type, args.dry_run)
    sys.stdout.write(prompt)


if __name__ == "__main__":
    main()
