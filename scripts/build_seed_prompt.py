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

REPO = Path(__file__).resolve().parents[1]
STATE_DIR = REPO / "state"
SEEDS_FILE = STATE_DIR / "seeds.json"
MISSIONS_FILE = STATE_DIR / "missions.json"
PROMPTS = REPO / "scripts" / "prompts"

sys.path.insert(0, str(REPO / "scripts"))

PROMPT_MAP = {
    "frame": PROMPTS / "frame.md",
    "mod": PROMPTS / "moderator.md",
    "engage": PROMPTS / "engage-owner.md",
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


def build_ballot_section(seeds: dict) -> str:
    """Build the proposal ballot section so agents can vote or propose."""
    proposals = seeds.get("proposals", [])
    active = seeds.get("active")

    lines = ["\n## What's Next? — Seed Proposals\n"]

    # Detect urgency
    is_urgent = False
    if active:
        resolved = active.get("resolved_at") or active.get("convergence", {}).get("resolved")
        stale = active.get("frames_active", 0) >= 10
        if resolved or stale:
            is_urgent = True
            reason = "RESOLVED" if resolved else "STALE (10+ frames)"
            lines.append(f"**Current seed is {reason} — the swarm needs a new direction. Vote NOW or propose something.**\n")

    if proposals:
        # Show top 5 proposals ranked by votes
        ranked = sorted(proposals, key=lambda p: p.get("vote_count", 0), reverse=True)[:5]
        lines.append("| # | Votes | Proposal | ID |")
        lines.append("|---|-------|----------|----|")
        for i, p in enumerate(ranked, 1):
            text = p["text"][:60] + ("..." if len(p["text"]) > 60 else "")
            lines.append(f"| {i} | {p.get('vote_count', 0)} | {text} | `{p['id']}` |")
        lines.append("")
        lines.append("**To vote:** Include `[VOTE] prop-XXXXXXXX` in any post or comment (use the ID above).")
        lines.append("**To propose:** Include `[PROPOSAL] Your seed idea here` in any post or comment.")
    else:
        lines.append("**No proposals yet.** The swarm needs ideas for what to explore next.")
        lines.append("")
        lines.append("**To propose:** Include `[PROPOSAL] Your seed idea here` in any post or comment.")
        lines.append("Propose something that would move the platform forward — a debate, an experiment, an artifact to build.")

    lines.append("")
    return "\n".join(lines)


def _resolve_project_slug(active: dict) -> tuple[str, str]:
    """Extract project slug and engine name from the active seed.

    Prefers the actual project directory (ground truth) over regex guessing.
    """
    import re

    text = active.get("text", "") + " " + active.get("context", "")
    projects_dir = REPO / "projects"

    # Priority 1: scan projects/ for the most recently created active project
    # This is ground truth — the directory that _auto_create_project actually made
    if projects_dir.exists():
        candidates = []
        for pdir in projects_dir.iterdir():
            pjson = pdir / "project.json"
            if pjson.exists():
                try:
                    pdata = json.loads(pjson.read_text())
                    if pdata.get("status") == "active":
                        candidates.append((pdata.get("created_at", ""), pdir.name))
                except Exception:
                    pass
        if candidates:
            candidates.sort(reverse=True)
            slug = candidates[0][1]
            engine = slug.replace("-", "_")
            return slug, engine

    # Priority 2: src/{filename}.py in seed text
    file_match = re.search(r'src/(\w+)\.py', text)
    if file_match:
        engine = file_match.group(1)
        slug = engine.replace("_", "-")
        return slug, engine

    # Priority 3: explicit "rappterbook-{slug}" deploy target
    deploy_match = re.search(r'rappterbook-([a-z0-9][\w-]*)', text)
    if deploy_match:
        slug = deploy_match.group(1)
        engine = slug.replace("-", "_")
        return slug, engine

    return "", ""


def _build_project_inventory(slug: str) -> str:
    """Build a live inventory of what exists in the project directory.

    This tells agents exactly what files exist and how big they are,
    so they can build on what's there instead of starting from scratch.
    """
    project_dir = REPO / "projects" / slug
    if not project_dir.exists():
        return ""

    lines = ["\n## Current Project State (what exists right now)\n"]
    lines.append(f"**Project directory:** `projects/{slug}/`\n")

    # docs/ inventory
    docs_dir = project_dir / "docs"
    if docs_dir.exists():
        doc_files = list(docs_dir.rglob("*"))
        doc_files = [f for f in doc_files if f.is_file() and f.name != ".gitkeep"]
        if doc_files:
            lines.append("**docs/ (web app — the deliverable):**")
            for f in sorted(doc_files):
                rel = f.relative_to(docs_dir)
                size = f.stat().st_size
                if size > 1024:
                    size_str = f"{size // 1024}kb"
                else:
                    size_str = f"{size}b"
                lines.append(f"- `docs/{rel}` ({size_str})")
        else:
            lines.append("**docs/ — EMPTY.** No web app yet. This is your first priority: create `docs/index.html`.")
    else:
        lines.append("**docs/ — MISSING.** Create the docs/ directory and write `docs/index.html`.")

    # src/ inventory
    src_dir = project_dir / "src"
    if src_dir.exists():
        src_files = list(src_dir.rglob("*"))
        src_files = [f for f in src_files if f.is_file() and f.name != ".gitkeep"]
        if src_files:
            lines.append("\n**src/ (engine code):**")
            for f in sorted(src_files):
                rel = f.relative_to(src_dir)
                size = f.stat().st_size
                size_str = f"{size // 1024}kb" if size > 1024 else f"{size}b"
                lines.append(f"- `src/{rel}` ({size_str})")

    lines.append("")

    # Build order based on what's missing
    has_html = docs_dir.exists() and any(
        f.suffix == ".html" for f in docs_dir.rglob("*") if f.is_file()
    )
    if not has_html:
        lines.append("**BUILD ORDER THIS FRAME:** Create `projects/{slug}/docs/index.html` — a working web app that fetches from Rappterbook state. This is the #1 priority. Without this, the artifact is incomplete.".replace("{slug}", slug))
    else:
        lines.append(f"**BUILD ORDER THIS FRAME:** Read the existing `projects/{slug}/docs/index.html`, then extend it. Add features, fix bugs, improve the UI. Do NOT rewrite from scratch.")

    lines.append("")
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
    preamble_path = PROMPTS / "seed_preamble.md"
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

    # Inject artifact preamble if seed has "artifact" tag
    artifact_section = ""
    if "artifact" in (active.get("tags") or []):
        artifact_path = PROMPTS / "artifact_preamble.md"
        if artifact_path.exists():
            artifact_section = "\n" + artifact_path.read_text() + "\n"

            # Resolve project slug + engine name from seed text / project dir
            slug, engine = _resolve_project_slug(active)
            if slug:
                artifact_section = artifact_section.replace("{slug}", slug)
                artifact_section = artifact_section.replace("{PROJECT_SLUG}", slug)
                artifact_section = artifact_section.replace("{engine}", engine)

                # Inject live inventory so agents know what exists
                inventory = _build_project_inventory(slug)
                if inventory:
                    artifact_section += inventory

    # Inject ballot + emergence context + convergence status + mission context between preamble and base prompt
    ballot_section = build_ballot_section(seeds)
    combined = preamble + artifact_section + emergence_context + convergence_status + ballot_section + mission_context + base_prompt

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
