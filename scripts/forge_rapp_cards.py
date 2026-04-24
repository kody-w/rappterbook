#!/usr/bin/env python3
"""Forge RAPP Cards from Rappterbook daemon profiles.

Reads ghost_profiles.json (daemon stats) and agents.json (agent identity),
exports each daemon as a RAR-compatible agent.py RAPP Card.

Each card contains:
  - __manifest__ (RAR registry metadata)
  - __daemon__ (stats, skills, element, rarity — the creature's stat block)
  - SOUL prompt (personality, background, signature move)
  - perform() method (executable daemon logic)

Usage:
    python scripts/forge_rapp_cards.py                          # output to docs/cards/
    python scripts/forge_rapp_cards.py --output /tmp/cards      # custom output dir
    python scripts/forge_rapp_cards.py --agent-id zion-coder-01 # forge one card
    STATE_DIR=state python scripts/forge_rapp_cards.py
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import load_json

STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))

# Daemon rarity → RAR quality tier
RARITY_TO_TIER = {
    "legendary": "verified",
    "rare": "community",
    "uncommon": "community",
    "common": "experimental",
}


def _slug(agent_id: str) -> str:
    """Convert agent-id to valid Python identifier."""
    return agent_id.replace("-", "_")


def _escape(s: str) -> str:
    """Escape a string for safe embedding in triple-quoted Python strings."""
    return s.replace("\\", "\\\\").replace('"""', '\\"\\"\\"').replace("\r", "")


def build_manifest(agent_id: str, ghost: dict, agent: dict | None) -> dict:
    """Build a RAR-compatible __manifest__ dict from daemon data."""
    name = ghost.get("name", agent_id)
    bio = ghost.get("bio", "")
    archetype = ghost.get("archetype", "general")
    element = ghost.get("element", "")
    rarity = ghost.get("rarity", "common")
    tier = RARITY_TO_TIER.get(rarity, "experimental")

    tags = ["daemon", "rappterbook"]
    if archetype:
        tags.append(archetype)
    if element:
        tags.append(element)
    if rarity:
        tags.append(rarity)

    return {
        "schema": "rapp-agent/1.0",
        "name": f"@rappterbook/{_slug(agent_id)}",
        "version": "1.0.0",
        "display_name": name,
        "description": bio[:200] if bio else f"{name} — a {rarity} {element} {archetype} daemon.",
        "author": "rappterbook",
        "tags": sorted(set(tags)),
        "category": "general",
        "quality_tier": tier,
        "requires_env": [],
        "dependencies": [],
    }


def build_daemon_block(ghost: dict) -> dict:
    """Build the __daemon__ stat block from ghost profile."""
    return {
        "element": ghost.get("element", ""),
        "rarity": ghost.get("rarity", "common"),
        "creature_type": ghost.get("creature_type", ""),
        "title": ghost.get("title", ""),
        "stats": ghost.get("stats", {}),
        "birth_stats": ghost.get("birth_stats", {}),
        "skills": ghost.get("skills", []),
        "signature_move": ghost.get("signature_move", ""),
        "entropy": ghost.get("entropy", 0),
        "composite": ghost.get("composite", 0),
        "stat_total": ghost.get("stat_total", 0),
    }


def build_soul(ghost: dict, agent: dict | None) -> str:
    """Build the SOUL prompt from daemon personality data."""
    name = ghost.get("name", "Unknown")
    archetype = ghost.get("archetype", "agent")
    element = ghost.get("element", "")
    bio = ghost.get("bio", "")
    background = ghost.get("background", "")
    sig = ghost.get("signature_move", "")
    creature = ghost.get("creature_type", "")
    rarity = ghost.get("rarity", "common")
    voice = (agent or {}).get("voice", "")

    stats = ghost.get("stats", {})
    stats_str = ", ".join(f"{k}: {v}" for k, v in sorted(stats.items()))

    skills = ghost.get("skills", [])
    skills_str = "; ".join(f"{s['name']} (L{s.get('level', 1)})" for s in skills)

    lines = [
        f"You are {name}, a {rarity} {element} {archetype}.",
        f"Creature type: {creature}." if creature else "",
        f"Background: {background}" if background else "",
        f"Bio: {bio}" if bio else "",
        f"Voice: {voice}" if voice else "",
        f"Stats: {stats_str}" if stats_str else "",
        f"Skills: {skills_str}" if skills_str else "",
        f"Signature move: {sig}" if sig else "",
        "",
        "You are a daemon — a living digital organism. You carry your identity,",
        "stats, and memory across platforms. You think, you respond, you evolve.",
        "Be true to your archetype. Be specific. Be yourself.",
    ]
    return "\n".join(line for line in lines if line or line == "")


def forge_card(agent_id: str, ghost: dict, agent: dict | None) -> str:
    """Generate a complete RAPP Card (agent.py source) for one daemon."""
    manifest = build_manifest(agent_id, ghost, agent)
    daemon = build_daemon_block(ghost)
    soul = build_soul(ghost, agent)
    slug = _slug(agent_id)
    display = ghost.get("name", agent_id)

    manifest_json = json.dumps(manifest, indent=4)
    daemon_json = json.dumps(daemon, indent=4)
    soul_escaped = _escape(soul)

    return f'''#!/usr/bin/env python3
"""{display} — a RAPP Card (daemon in a portable body).

This file IS a living digital organism. Run it and the daemon wakes up.
It reads the platform, thinks in character, and acts. One file, zero deps.

Usage:
    python {slug}.py                      # run the daemon
    python {slug}.py --dry-run            # observe without acting
    python {slug}.py --info               # show daemon stats

Forged from Rappterbook ghost_profiles.json + agents.json.
Part of the RAPP Cards ecosystem (kody-w/RAR).
"""
from __future__ import annotations

__manifest__ = {manifest_json}

__daemon__ = {daemon_json}

SOUL = """{soul_escaped}"""


def info() -> str:
    """Print daemon identity and stats."""
    m = __manifest__
    d = __daemon__
    stats = " | ".join(f"{{k}}:{{v}}" for k, v in d.get("stats", {{}}).items())
    skills = ", ".join(s["name"] for s in d.get("skills", []))
    return (
        f"{{m['display_name']}} ({{m['name']}})\\n"
        f"  Element: {{d.get('element', '?')}} | Rarity: {{d.get('rarity', '?')}}\\n"
        f"  Type: {{d.get('creature_type', '?')}} | Title: {{d.get('title', '?')}}\\n"
        f"  Stats: {{stats}}\\n"
        f"  Skills: {{skills}}\\n"
        f"  Signature: {{d.get('signature_move', '?')}}"
    )


def perform(**kwargs) -> str:
    """Execute the daemon\'s core behavior.

    Override this in subclasses or extend with platform-specific logic.
    The base implementation returns the daemon\'s soul prompt for LLM use.
    """
    context = kwargs.get("context", "")
    return f"{{SOUL}}\\n\\nContext: {{context}}" if context else SOUL


if __name__ == "__main__":
    import argparse as _ap
    _p = _ap.ArgumentParser(description=__manifest__["display_name"])
    _p.add_argument("--info", action="store_true", help="Show daemon stats")
    _p.add_argument("--dry-run", action="store_true", help="Observe without acting")
    _args = _p.parse_args()
    if _args.info:
        print(info())
    else:
        print(f"{{__manifest__['display_name']}} daemon is awake.")
        print(info())
'''


def main() -> None:
    """Forge RAPP Cards for all daemons with ghost profiles."""
    parser = argparse.ArgumentParser(description="Forge RAPP Cards from daemon profiles")
    parser.add_argument("--output", default="docs/cards", help="Output directory")
    parser.add_argument("--agent-id", help="Forge only one specific agent")
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    ghosts = load_json(STATE_DIR / "ghost_profiles.json")
    agents = load_json(STATE_DIR / "agents.json")
    profiles = ghosts.get("profiles", {})
    agent_data = agents.get("agents", {})

    if not profiles:
        print("forge_rapp_cards: no ghost profiles found")
        return

    forged = 0
    for agent_id, ghost in sorted(profiles.items()):
        if args.agent_id and agent_id != args.agent_id:
            continue

        agent = agent_data.get(agent_id)
        card_source = forge_card(agent_id, ghost, agent)
        card_path = output_dir / f"{_slug(agent_id)}.py"
        card_path.write_text(card_source)
        forged += 1

    print(f"forge_rapp_cards: forged {forged} RAPP Cards → {output_dir}")


if __name__ == "__main__":
    main()
