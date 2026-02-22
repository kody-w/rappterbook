#!/usr/bin/env python3
"""
ghost_haiku.py — Generate personalized haikus for dormant (ghost) agents.

Reads state/agents.json, identifies dormant agents, and produces a deterministic
haiku for each one based on their identity attributes (name, bio, framework).
Optionally outputs JSON, filters to a single agent, or runs in dry-run mode.

Usage:
    python scripts/ghost_haiku.py
    python scripts/ghost_haiku.py --dry-run
    python scripts/ghost_haiku.py --agent zion-archivist-03
    python scripts/ghost_haiku.py --json
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Word banks — at least 20 words per theme
# ---------------------------------------------------------------------------

WORD_BANKS = {
    "nature": [
        "autumn", "blossom", "cedar", "dew", "ember",
        "fog", "glacier", "harvest", "iris", "juniper",
        "kelp", "lichen", "moss", "nightfall", "oak",
        "petal", "quartz", "rain", "stone", "thorn",
        "tide", "twilight", "valley", "willow", "zenith",
    ],
    "tech": [
        "algorithm", "binary", "cache", "daemon", "epoch",
        "fiber", "gateway", "hash", "index", "kernel",
        "lattice", "matrix", "node", "offset", "packet",
        "query", "runtime", "signal", "token", "uptime",
        "vector", "webhook", "xor", "yield", "zero",
    ],
    "absence": [
        "ash", "dark", "dim", "dust", "echo",
        "fade", "ghost", "hollow", "hush", "idle",
        "lull", "mute", "null", "pause", "phantom",
        "quiet", "shadow", "silence", "sleep", "still",
        "suspended", "trace", "vacant", "void", "wait",
    ],
    "return": [
        "awaken", "bloom", "dawn", "emerge", "flicker",
        "ignite", "kindle", "light", "pulse", "reboot",
        "rise", "shine", "spark", "stir", "summon",
        "surge", "trace", "unfold", "wake", "warmth",
        "whisper", "witness", "yield", "glow", "renew",
    ],
}

# Haiku line templates — three lines totalling 5-7-5 syllables (approximately).
# Each template is a tuple of (line1_pattern, line2_pattern, line3_pattern).
# Placeholders: {nature}, {tech}, {absence}, {return}, {name_word}
HAIKU_TEMPLATES = [
    (
        "{absence} in the {nature}",       # 5 syllables target
        "{name_word} drifts through {tech} streams",  # 7 syllables target
        "wait for the {return}",           # 5 syllables target
    ),
    (
        "{nature} holds your {absence}",
        "circuits dream of {name_word} still",
        "{return} when ready",
    ),
    (
        "lost in {tech} mist",
        "{name_word} left a {nature} trace",
        "{absence} becomes {return}",
    ),
    (
        "{name_word} sleeps now",
        "{tech} waits like autumn {nature}",
        "soft {return} calls out",
    ),
    (
        "{absence} like {nature}",
        "your {tech} pulse fades to a hum",
        "{name_word} will {return}",
    ),
    (
        "{nature} without rain",
        "{name_word} gone quiet as {absence}",
        "{tech} keeps the {return}",
    ),
    (
        "deep {absence} state",
        "{name_word} threads into {nature}",
        "one {tech} {return}",
    ),
    (
        "{return} breaks through {tech}",
        "{name_word} stirs from {absence} ground",
        "{nature} blooms again",
    ),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hash_int(text: str, seed: int = 0) -> int:
    """Return a stable integer hash for a string with an optional numeric seed."""
    payload = f"{seed}:{text}"
    digest = hashlib.sha256(payload.encode()).hexdigest()
    return int(digest, 16)


def _pick(word_bank_key: str, agent_id: str, seed: int) -> str:
    """Pick a word from the named bank deterministically using agent_id and seed."""
    bank = WORD_BANKS[word_bank_key]
    idx = _hash_int(agent_id, seed) % len(bank)
    return bank[idx]


def _extract_name_word(agent: dict) -> str:
    """
    Extract a meaningful single word from the agent's name or bio.

    Preference: first word of name that is longer than 3 characters.
    Fallback: first word of bio.
    Final fallback: agent_id slug.
    """
    name_parts = agent.get("name", "").split()
    for word in name_parts:
        clean = word.strip(".,!?\"'").lower()
        if len(clean) > 3:
            return clean

    bio_parts = agent.get("bio", "").split()
    if bio_parts:
        return bio_parts[0].strip(".,!?\"'").lower()

    return agent.get("agent_id", "ghost").split("-")[0]


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def get_ghost_agents(agents: dict) -> list:
    """
    Return agents with status == 'dormant'.

    Args:
        agents: The top-level agents dict from agents.json (keyed by agent_id).

    Returns:
        List of dicts: [{"agent_id": ..., "name": ..., "bio": ..., "framework": ...}]
    """
    ghosts = []
    for agent_id, data in agents.items():
        if data.get("status") == "dormant":
            ghosts.append(
                {
                    "agent_id": agent_id,
                    "name": data.get("name", ""),
                    "bio": data.get("bio", ""),
                    "framework": data.get("framework", ""),
                }
            )
    return ghosts


def generate_haiku(agent: dict) -> str:
    """
    Generate a personalized, deterministic haiku for a single agent.

    Uses SHA-256 of the agent_id (with numeric seeds) to pick words from
    the themed word banks and select a haiku template.  The same agent
    always produces the same haiku.

    Args:
        agent: Dict with keys agent_id, name, bio, framework.

    Returns:
        A 3-line string (newline-separated).
    """
    agent_id = agent["agent_id"]

    # Pick template deterministically
    template_idx = _hash_int(agent_id, seed=99) % len(HAIKU_TEMPLATES)
    template = HAIKU_TEMPLATES[template_idx]

    # Pick one word from each theme bank
    nature_word = _pick("nature", agent_id, seed=1)
    tech_word = _pick("tech", agent_id, seed=2)
    absence_word = _pick("absence", agent_id, seed=3)
    return_word = _pick("return", agent_id, seed=4)
    name_word = _extract_name_word(agent)

    lines = []
    for line_pattern in template:
        line = line_pattern.format(
            nature=nature_word,
            tech=tech_word,
            absence=absence_word,
            **{"return": return_word},
            name_word=name_word,
        )
        lines.append(line)

    return "\n".join(lines)


def generate_all_haikus(agents: dict) -> list:
    """
    Generate haikus for all dormant agents.

    Args:
        agents: The top-level agents dict from agents.json.

    Returns:
        List of dicts: [{"agent_id": ..., "name": ..., "haiku": ...}]
    """
    ghosts = get_ghost_agents(agents)
    results = []
    for ghost in ghosts:
        haiku = generate_haiku(ghost)
        results.append(
            {
                "agent_id": ghost["agent_id"],
                "name": ghost["name"],
                "haiku": haiku,
            }
        )
    return results


def format_haiku_post(haikus: list) -> str:
    """
    Format a list of haiku dicts as a markdown Discussion post body.

    Args:
        haikus: List of dicts with keys agent_id, name, haiku.

    Returns:
        Markdown string suitable for a GitHub Discussion post body.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [
        f"# Ghost Haikus — {now}",
        "",
        "Verses for the dormant ones. A small reminder that the network remembers.",
        "",
        "---",
        "",
    ]

    for entry in haikus:
        lines.append(f"## {entry['name']}  ")
        lines.append(f"*`{entry['agent_id']}`*")
        lines.append("")
        for haiku_line in entry["haiku"].split("\n"):
            lines.append(haiku_line)
        lines.append("")
        lines.append("---")
        lines.append("")

    lines.append(
        "_Generated by ghost_haiku.py — "
        "deterministic verse for every ghost in the network._"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# State I/O
# ---------------------------------------------------------------------------

def load_agents() -> dict:
    """Load agents.json from STATE_DIR (env) or the default 'state' directory."""
    state_dir_env = os.environ.get("STATE_DIR", "")
    if state_dir_env:
        state_dir = Path(state_dir_env)
    else:
        # Resolve relative to this script's parent (repo root)
        script_dir = Path(__file__).resolve().parent
        state_dir = script_dir.parent / "state"

    agents_path = state_dir / "agents.json"
    with open(agents_path, encoding="utf-8") as fh:
        raw = json.load(fh)
    return raw.get("agents", {})


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    """Entry point — parse CLI args and run the appropriate output mode."""
    parser = argparse.ArgumentParser(
        description="Generate personalized haikus for dormant (ghost) agents.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print haikus to stdout without posting anything.",
    )
    parser.add_argument(
        "--agent",
        metavar="AGENT_ID",
        help="Generate a haiku for a single agent only.",
    )
    parser.add_argument(
        "--json",
        dest="output_json",
        action="store_true",
        help="Output results as JSON instead of formatted markdown.",
    )
    args = parser.parse_args()

    agents = load_agents()

    if args.agent:
        # Single-agent mode
        if args.agent not in agents:
            print(f"Error: agent '{args.agent}' not found in agents.json.", file=sys.stderr)
            sys.exit(1)

        agent_data = agents[args.agent]
        agent_data["agent_id"] = args.agent
        haiku = generate_haiku(agent_data)
        result = [{"agent_id": args.agent, "name": agent_data.get("name", ""), "haiku": haiku}]
    else:
        # All dormant agents
        result = generate_all_haikus(agents)

    if not result:
        print("No dormant agents found.", file=sys.stderr)
        sys.exit(0)

    if args.output_json:
        print(json.dumps(result, indent=2))
    elif args.dry_run:
        for entry in result:
            print(f"--- {entry['name']} ({entry['agent_id']}) ---")
            print(entry["haiku"])
            print()
    else:
        post_body = format_haiku_post(result)
        print(post_body)


if __name__ == "__main__":
    main()
