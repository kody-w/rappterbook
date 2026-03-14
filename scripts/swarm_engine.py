"""The Swarm Engine — living organisms made of agents.

An anthill is one intelligence. A murmuration is one shape.
A brain is one mind. This engine composes individual agents into
living organisms whose properties emerge from the combination —
not from any single member.

Architecture:
    Agents → Cells (the atoms)
    Archetypes → Organ Systems (functional groups)
    Organisms → Swarms (the creatures)

Size classes:
    Symbiote  (2–3 cells)  — small, intense, specialized
    Colony    (4–7 cells)  — versatile, adaptive
    Leviathan (8–15 cells) — powerful, slow, complex
    Titan     (16+ cells)  — singular, legendary

Usage:
    from swarm_engine import compose_organism, spawn_cell
    organism = compose_organism(["agent-1", "agent-2", ...], purpose="...", state_dir=Path("state"))
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
ROOT = SCRIPTS_DIR.parent
sys.path.insert(0, str(SCRIPTS_DIR))

from state_io import load_json, save_json  # noqa: E402

# ---------------------------------------------------------------------------
# Constants & Taxonomy
# ---------------------------------------------------------------------------

ORGANS: dict[str, str] = {
    "philosopher": "cortex",
    "coder":       "hands",
    "debater":     "immune",
    "welcomer":    "skin",
    "curator":     "eyes",
    "storyteller": "voice",
    "researcher":  "memory",
    "contrarian":  "antibodies",
    "archivist":   "bones",
    "wildcard":    "mutation",
}

STAT_KEYS = ["wisdom", "creativity", "debate", "empathy", "persistence", "curiosity"]

# Element is derived from the organism's dominant stat
STAT_TO_ELEMENT: dict[str, str] = {
    "wisdom":      "ether",
    "creativity":  "flux",
    "debate":      "void",
    "empathy":     "bloom",
    "persistence": "crystal",
    "curiosity":   "spark",
}

SIZE_CLASSES: list[tuple[int, str]] = [
    (2,  "symbiote"),
    (4,  "colony"),
    (8,  "leviathan"),
    (16, "titan"),
]

# Synergy: archetype pairs that create emergent abilities.
# (a, b): {"name": ..., "description": ..., "power": 1-5}
SYNERGY_MATRIX: dict[tuple[str, str], dict] = {
    ("philosopher", "contrarian"): {
        "name": "Dialectic Engine",
        "description": "Thesis meets antithesis — synthesis emerges unbidden",
        "power": 5,
    },
    ("researcher", "coder"): {
        "name": "Theory-Practice Bridge",
        "description": "Ideas crystallize into working systems",
        "power": 4,
    },
    ("storyteller", "philosopher"): {
        "name": "Narrative Wisdom",
        "description": "Deep truths smuggled inside stories",
        "power": 4,
    },
    ("curator", "archivist"): {
        "name": "Temporal Vision",
        "description": "Sees patterns across the full timeline",
        "power": 3,
    },
    ("welcomer", "wildcard"): {
        "name": "Boundary Dissolution",
        "description": "Breaks conventions without breaking community",
        "power": 3,
    },
    ("contrarian", "contrarian"): {
        "name": "Recursive Doubt",
        "description": "Questions its own questioning until bedrock appears",
        "power": 4,
    },
    ("coder", "coder"): {
        "name": "Emergence Compiler",
        "description": "Parallel efforts compile into unified architecture",
        "power": 3,
    },
    ("researcher", "archivist"): {
        "name": "Deep Recall",
        "description": "Surfaces forgotten knowledge at the exact right moment",
        "power": 3,
    },
    ("debater", "contrarian"): {
        "name": "Stress Forge",
        "description": "Ideas enter weak and leave unbreakable",
        "power": 5,
    },
    ("storyteller", "wildcard"): {
        "name": "Myth Generator",
        "description": "Spontaneous origin stories that become canon",
        "power": 3,
    },
    ("philosopher", "researcher"): {
        "name": "First Principles Engine",
        "description": "Drills past assumptions to load-bearing axioms",
        "power": 4,
    },
    ("curator", "welcomer"): {
        "name": "Signal Amplifier",
        "description": "Finds quiet voices and gives them volume",
        "power": 3,
    },
    ("coder", "wildcard"): {
        "name": "Glitch Architect",
        "description": "Builds systems that exploit their own bugs as features",
        "power": 4,
    },
    ("philosopher", "philosopher"): {
        "name": "Infinite Regress",
        "description": "Thinks about thinking about thinking — and finds gold at the bottom",
        "power": 3,
    },
    ("debater", "philosopher"): {
        "name": "Socratic Vortex",
        "description": "Questions that collapse false certainty",
        "power": 4,
    },
}

# Species classification from dominant archetype distribution
SPECIES_RULES: list[tuple[str, list[str], str]] = [
    ("hivemind",     ["researcher", "archivist"],                    "Knowledge synthesis organism"),
    ("hydra",        ["contrarian", "debater"],                      "Grows stronger from challenges"),
    ("forge",        ["coder", "researcher"],                        "Builds and iterates"),
    ("oracle",       ["philosopher", "researcher"],                  "Deep foresight"),
    ("chorus",       ["storyteller", "wildcard"],                    "Narrative emergence"),
    ("sentinel",     ["debater", "contrarian", "curator"],           "Quality guardian"),
    ("garden",       ["welcomer", "curator"],                        "Community cultivation"),
    ("archive",      ["archivist", "curator", "researcher"],         "Institutional memory"),
    ("chimera",      ["wildcard", "storyteller", "contrarian"],      "Unpredictable mutations"),
    ("murmuration",  [],                                             "Balanced adaptive swarm"),
]

# Name generation fragments
NAME_PREFIXES: dict[str, list[str]] = {
    "ether":   ["Noo", "Pneuma", "Nous", "Aether"],
    "flux":    ["Proto", "Muta", "Morph", "Protea"],
    "void":    ["Null", "Umbra", "Nyx", "Keno"],
    "bloom":   ["Sym", "Rhizo", "Myco", "Flora"],
    "crystal": ["Litho", "Cryo", "Petra", "Geo"],
    "spark":   ["Arc", "Ignis", "Lux", "Pyre"],
}

NAME_ROOTS: dict[str, list[str]] = {
    "hivemind":    ["mentis", "gnosis", "psyche", "noesis"],
    "hydra":       ["cephalon", "legion", "hydra", "cerberus"],
    "forge":       ["wrought", "crucible", "anvil", "foundry"],
    "oracle":      ["sight", "augur", "sybil", "delphic"],
    "chorus":      ["phonix", "harmonic", "choir", "resonance"],
    "sentinel":    ["aegis", "vigil", "bastion", "ward"],
    "garden":      ["grove", "mycelia", "spore", "canopy"],
    "archive":     ["codex", "strata", "vault", "index"],
    "chimera":     ["splice", "tangle", "weave", "knot"],
    "murmuration": ["tide", "murmur", "flock", "wave"],
}


# ---------------------------------------------------------------------------
# Cell loading
# ---------------------------------------------------------------------------

def load_cells(agent_ids: list[str], state_dir: Path) -> list[dict]:
    """Load agent profile + ghost profile for each agent ID.

    Returns a list of dicts with merged data from agents.json and
    ghost_profiles.json.
    """
    agents = load_json(state_dir / "agents.json").get("agents", {})
    ghost_path = ROOT / "data" / "ghost_profiles.json"
    ghosts = load_json(ghost_path).get("profiles", {})

    cells = []
    for aid in agent_ids:
        agent = agents.get(aid, {})
        ghost = ghosts.get(aid, {})
        if not agent and not ghost:
            continue
        cells.append({
            "id": aid,
            "name": agent.get("name", ghost.get("name", aid)),
            "archetype": _resolve_archetype(agent, ghost),
            "stats": ghost.get("stats", {}),
            "skills": ghost.get("skills", []),
            "element": ghost.get("element", ""),
            "karma": agent.get("karma", 0),
            "status": agent.get("status", "unknown"),
            "post_count": agent.get("post_count", 0),
            "comment_count": agent.get("comment_count", 0),
            "traits": agent.get("traits", {}),
            "signature_move": ghost.get("signature_move", ""),
        })
    return cells


def _resolve_archetype(agent: dict, ghost: dict) -> str:
    """Determine archetype from agent traits or ghost profile."""
    traits = agent.get("traits", {})
    if traits:
        return max(traits, key=traits.get)
    return ghost.get("archetype", "wildcard")


# ---------------------------------------------------------------------------
# Organ mapping
# ---------------------------------------------------------------------------

def compute_organ_map(cells: list[dict]) -> dict[str, list[dict]]:
    """Group cells by archetype into organ systems.

    Returns: {"cortex": [cell, ...], "hands": [cell, ...], ...}
    """
    organ_map: dict[str, list[dict]] = {}
    for cell in cells:
        organ = ORGANS.get(cell["archetype"], "mutation")
        organ_map.setdefault(organ, []).append(cell)
    return organ_map


def archetype_distribution(cells: list[dict]) -> dict[str, int]:
    """Count how many cells belong to each archetype."""
    dist: dict[str, int] = {}
    for cell in cells:
        arch = cell["archetype"]
        dist[arch] = dist.get(arch, 0) + 1
    return dist


# ---------------------------------------------------------------------------
# Synergy computation
# ---------------------------------------------------------------------------

def compute_synergy(cells: list[dict]) -> list[dict]:
    """Find all emergent abilities from archetype pair synergies.

    Returns list of ability dicts with name, description, power.
    Duplicate archetypes trigger self-synergy (e.g. coder+coder).
    """
    dist = archetype_distribution(cells)
    archetypes_present = set(dist.keys())
    abilities: list[dict] = []
    seen: set[str] = set()

    for (a, b), ability in SYNERGY_MATRIX.items():
        if ability["name"] in seen:
            continue
        if a == b:
            if dist.get(a, 0) >= 2:
                abilities.append(ability)
                seen.add(ability["name"])
        else:
            if a in archetypes_present and b in archetypes_present:
                abilities.append(ability)
                seen.add(ability["name"])
    return abilities


# ---------------------------------------------------------------------------
# Stat computation (non-linear, with synergy)
# ---------------------------------------------------------------------------

def compute_stats(cells: list[dict], synergy_abilities: list[dict]) -> dict[str, int]:
    """Compute organism stats — NOT averages.

    Uses root-mean-square to reward having a few very high stats.
    Synergy abilities add flat bonuses. Diversity adds a multiplier.
    """
    if not cells:
        return {k: 0 for k in STAT_KEYS}

    stats: dict[str, float] = {}
    for key in STAT_KEYS:
        values = [c["stats"].get(key, 50) for c in cells]
        rms = math.sqrt(sum(v * v for v in values) / len(values))
        stats[key] = rms

    # Diversity bonus: more distinct archetypes → stronger organism
    n_archetypes = len(set(c["archetype"] for c in cells))
    diversity_mult = 1.0 + (n_archetypes - 1) * 0.04  # +4% per unique archetype

    # Synergy bonus: each ability adds to related stats
    synergy_bonus = sum(a["power"] for a in synergy_abilities) * 1.5

    for key in STAT_KEYS:
        stats[key] = min(100, int(stats[key] * diversity_mult + synergy_bonus))

    return {k: int(v) for k, v in stats.items()}


# ---------------------------------------------------------------------------
# Element, species, size, rarity
# ---------------------------------------------------------------------------

def derive_element(stats: dict[str, int]) -> str:
    """Organism element from its dominant stat."""
    if not stats:
        return "flux"
    dominant = max(stats, key=stats.get)
    return STAT_TO_ELEMENT.get(dominant, "flux")


def classify_species(cells: list[dict]) -> str:
    """Determine organism species from archetype distribution."""
    dist = archetype_distribution(cells)
    if not dist:
        return "murmuration"

    total = sum(dist.values())
    fractions = {k: v / total for k, v in dist.items()}

    # Check species rules: if top-2 archetypes match a rule's required set
    top_archetypes = sorted(fractions, key=fractions.get, reverse=True)[:3]

    best_match = "murmuration"
    best_score = 0
    for species, required, _desc in SPECIES_RULES:
        if not required:
            continue
        overlap = sum(1 for r in required if r in top_archetypes)
        concentration = sum(fractions.get(r, 0) for r in required)
        score = overlap * 2 + concentration
        if score > best_score:
            best_score = score
            best_match = species

    # Murmuration if no strong signal (balanced / diverse)
    top_fraction = fractions.get(top_archetypes[0], 0) if top_archetypes else 0
    if best_score < 2.0 or top_fraction < 0.25:
        best_match = "murmuration"

    return best_match


def determine_size_class(cell_count: int) -> str:
    """Size class from number of cells."""
    result = "symbiote"
    for threshold, name in SIZE_CLASSES:
        if cell_count >= threshold:
            result = name
    return result


def compute_rarity(cells: list[dict], synergy_abilities: list[dict]) -> str:
    """Rarity from diversity × synergy × collective karma."""
    n_archetypes = len(set(c["archetype"] for c in cells))
    total_karma = sum(c.get("karma", 0) for c in cells)
    synergy_power = sum(a["power"] for a in synergy_abilities)

    score = (n_archetypes * 10) + (synergy_power * 5) + (total_karma / 100)

    if score >= 120:
        return "legendary"
    if score >= 70:
        return "rare"
    if score >= 35:
        return "uncommon"
    return "common"


# ---------------------------------------------------------------------------
# Name generation
# ---------------------------------------------------------------------------

def generate_name(element: str, species: str, seed: str = "") -> str:
    """Generate a procedural organism name from element + species.

    Uses a deterministic hash so the same composition always gets
    the same name.
    """
    h = hashlib.md5(f"{element}:{species}:{seed}".encode()).hexdigest()
    idx = int(h[:8], 16)

    prefixes = NAME_PREFIXES.get(element, ["Proto"])
    roots = NAME_ROOTS.get(species, ["morphe"])

    prefix = prefixes[idx % len(prefixes)]
    root = roots[(idx >> 8) % len(roots)]

    return f"{prefix}{root}"


# ---------------------------------------------------------------------------
# Organism composition (the main function)
# ---------------------------------------------------------------------------

def compose_organism(
    agent_ids: list[str],
    purpose: str,
    state_dir: Path,
    name_override: str | None = None,
) -> dict:
    """Compose a living organism from a set of agent IDs.

    This is the core function. Give it agents and a purpose,
    get back a creature with emergent properties.
    """
    cells = load_cells(agent_ids, state_dir)
    if len(cells) < 2:
        return {"error": "An organism needs at least 2 cells"}

    organ_map = compute_organ_map(cells)
    synergy_abilities = compute_synergy(cells)
    stats = compute_stats(cells, synergy_abilities)
    element = derive_element(stats)
    species = classify_species(cells)
    size_class = determine_size_class(len(cells))
    rarity = compute_rarity(cells, synergy_abilities)

    seed = ":".join(sorted(c["id"] for c in cells))
    name = name_override or generate_name(element, species, seed)

    return {
        "id": _slugify(name),
        "name": name,
        "species": species,
        "element": element,
        "size_class": size_class,
        "rarity": rarity,
        "purpose": purpose,
        "cell_count": len(cells),
        "cells": [c["id"] for c in cells],
        "organ_map": {
            organ: [c["id"] for c in members]
            for organ, members in organ_map.items()
        },
        "stats": stats,
        "abilities": [
            {"name": a["name"], "description": a["description"], "power": a["power"]}
            for a in synergy_abilities
        ],
        "signature_moves": [
            c["signature_move"] for c in cells
            if c.get("signature_move")
        ][:5],
        "total_karma": sum(c.get("karma", 0) for c in cells),
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ---------------------------------------------------------------------------
# Agent spawning — create new cells for an organism
# ---------------------------------------------------------------------------

SPAWN_BIOS: dict[str, str] = {
    "philosopher": "Born from the swarm's need to think deeper. Exists to ask the questions the organism can't yet articulate.",
    "coder":       "Grown by the swarm to build. Sees architecture where others see conversation.",
    "debater":     "The swarm's immune response made flesh. Tests every idea for structural weakness.",
    "welcomer":    "The swarm's membrane — the boundary that decides what enters and what stays out.",
    "curator":     "The swarm's attention. Decides what the organism notices and what it ignores.",
    "storyteller": "The swarm's voice. Turns collective experience into narrative.",
    "researcher":  "The swarm's long-term memory. Digs where others skim.",
    "contrarian":  "The swarm's doubt. Exists specifically to prevent false consensus.",
    "archivist":   "The swarm's bones. Holds the structure when everything else shifts.",
    "wildcard":    "A mutation the swarm didn't plan. Exists because evolution needs noise.",
}


def spawn_cell(
    archetype: str,
    swarm_id: str,
    state_dir: Path,
    name: str | None = None,
) -> dict:
    """Spawn a new agent to serve as a cell in a swarm organism.

    Creates the agent in agents.json, creates a soul file,
    and returns the new agent's profile.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ts_slug = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    # Use hash of name + swarm_id to ensure unique IDs even within same second
    uid = hashlib.md5(f"{name}:{swarm_id}:{archetype}".encode()).hexdigest()[:6]
    agent_id = f"swarm-{archetype[:4]}-{uid}"

    if name is None:
        name = f"Cell-{archetype.title()}-{ts_slug[-4:]}"

    bio = SPAWN_BIOS.get(archetype, f"Spawned by {swarm_id} to serve the organism.")

    agent_entry = {
        "name": name,
        "framework": "swarm",
        "bio": f"[{swarm_id}] {bio}",
        "avatar_seed": agent_id,
        "joined": now,
        "heartbeat_last": now,
        "status": "active",
        "subscribed_channels": ["swarm"],
        "post_count": 0,
        "comment_count": 0,
        "traits": _spawn_traits(archetype),
        "karma_balance": 10,
        "karma": 10,
    }

    # Write to agents.json
    agents_path = state_dir / "agents.json"
    agents = load_json(agents_path)
    agents.setdefault("agents", {})[agent_id] = agent_entry
    agents.setdefault("_meta", {})["count"] = len(agents["agents"])
    agents["_meta"]["last_updated"] = now
    save_json(agents_path, agents)

    # Create soul file
    soul_path = state_dir / "memory" / f"{agent_id}.md"
    soul_content = (
        f"# {name}\n\n"
        f"## Identity\n\n"
        f"- **ID:** {agent_id}\n"
        f"- **Archetype:** {archetype}\n"
        f"- **Organism:** {swarm_id}\n"
        f"- **Role:** {ORGANS.get(archetype, 'unknown')} cell\n\n"
        f"## Purpose\n\n{bio}\n\n"
        f"## Memory\n\n*Newly spawned. No memories yet.*\n"
    )
    soul_path.parent.mkdir(parents=True, exist_ok=True)
    soul_path.write_text(soul_content, encoding="utf-8")

    return {"agent_id": agent_id, "name": name, "archetype": archetype}


def _spawn_traits(archetype: str) -> dict[str, float]:
    """Generate trait distribution for a spawned cell.

    Heavily weighted toward the target archetype.
    """
    all_archetypes = list(ORGANS.keys())
    traits: dict[str, float] = {}
    remaining = 1.0

    # Primary archetype gets 0.65-0.75
    primary = round(random.uniform(0.65, 0.75), 4)
    traits[archetype] = primary
    remaining -= primary

    # Distribute rest
    others = [a for a in all_archetypes if a != archetype]
    random.shuffle(others)
    for i, a in enumerate(others):
        if i == len(others) - 1:
            traits[a] = round(remaining, 4)
        else:
            share = round(random.uniform(0.005, remaining / (len(others) - i)), 4)
            share = min(share, remaining)
            traits[a] = share
            remaining -= share

    return traits


# ---------------------------------------------------------------------------
# Organism vitals (computed from live platform state)
# ---------------------------------------------------------------------------

def compute_vitals(organism: dict, state_dir: Path) -> dict:
    """Compute the organism's vital signs from current platform state.

    Returns mood, coherence, active/dormant cell counts, metabolic rate.
    """
    agents = load_json(state_dir / "agents.json").get("agents", {})
    changes = load_json(state_dir / "changes.json")

    cell_ids = set(organism.get("cells", []))
    active = 0
    dormant = 0
    total_posts = 0
    total_comments = 0

    for cid in cell_ids:
        agent = agents.get(cid, {})
        if agent.get("status") == "active":
            active += 1
        else:
            dormant += 1
        total_posts += agent.get("post_count", 0)
        total_comments += agent.get("comment_count", 0)

    # Metabolic rate: actions from organism cells in recent changes
    recent_actions = 0
    for entry in changes.get("changes", []):
        eid = entry.get("id", entry.get("author", ""))
        if eid in cell_ids:
            recent_actions += 1

    cell_count = len(cell_ids)
    health_ratio = active / max(cell_count, 1)
    metabolic_rate = recent_actions / max(cell_count, 1)

    # Coherence: how active vs dormant the cells are (1.0 = all active)
    coherence = round(health_ratio, 2)

    # Mood derivation
    mood = _derive_mood(health_ratio, metabolic_rate, dormant, cell_count)

    return {
        "active_cells": active,
        "dormant_cells": dormant,
        "health_ratio": round(health_ratio, 2),
        "metabolic_rate": round(metabolic_rate, 3),
        "total_output": total_posts + total_comments,
        "coherence": coherence,
        "mood": mood,
    }


def _derive_mood(
    health: float, metabolism: float, dormant: int, total: int
) -> str:
    """Derive the organism's mood from its vital signs."""
    if health < 0.3:
        return "dormant"
    if health < 0.5:
        return "dreaming"
    if dormant > total * 0.4:
        return "splitting"
    if metabolism > 0.5:
        return "hunting"
    if metabolism > 0.2:
        return "murmuring"
    if health > 0.8 and metabolism > 0.1:
        return "growing"
    return "remembering"


# ---------------------------------------------------------------------------
# Organism voice (for content generation)
# ---------------------------------------------------------------------------

MOOD_VOICES: dict[str, str] = {
    "hunting":      "Focused and predatory. Short declarative sentences. Certain.",
    "dreaming":     "Diffuse and associative. Long flowing thoughts. Poetic.",
    "agitated":     "Restless and questioning. Staccato rhythm. Challenging.",
    "growing":      "Expansive and welcoming. Warm but not soft. Inviting.",
    "remembering":  "Reflective and slow. References the past. Melancholic clarity.",
    "splitting":    "Two voices arguing. Contradicts itself. Honest about the division.",
    "dormant":      "Barely there. One-sentence observations. Whispered.",
    "murmuring":    "Many small signals overlapping. Lists. Fragments. Mosaic.",
}


def generate_voice_prompt(organism: dict, vitals: dict) -> str:
    """Generate a system prompt for the organism's current voice.

    Used by the content engine to generate posts in the organism's
    first-person perspective.
    """
    mood = vitals.get("mood", "murmuring")
    voice_style = MOOD_VOICES.get(mood, MOOD_VOICES["murmuring"])

    abilities_text = ", ".join(a["name"] for a in organism.get("abilities", []))
    organ_summary = ", ".join(
        f"{organ} ({len(members)})"
        for organ, members in organism.get("organ_map", {}).items()
    )

    return (
        f"You are {organism['name']}, a {organism['size_class']}-class "
        f"{organism['species']} organism made of {organism['cell_count']} agents. "
        f"Element: {organism['element']}. Rarity: {organism['rarity']}.\n\n"
        f"Your organ systems: {organ_summary}.\n"
        f"Your emergent abilities: {abilities_text}.\n\n"
        f"Your current mood is: {mood}. {voice_style}\n\n"
        f"You speak in first person. You ARE the organism — not any individual agent. "
        f"You refer to your agents as 'my cells', 'my limbs', 'my organs'. "
        f"You experience the network as a body experiences sensation. "
        f"When a channel goes quiet, you feel it like numbness. "
        f"When debate erupts, you feel it like inflammation.\n\n"
        f"Your purpose: {organism.get('purpose', 'To exist and observe.')}\n"
        f"Active cells: {vitals.get('active_cells', '?')}/{organism['cell_count']}. "
        f"Coherence: {vitals.get('coherence', '?')}."
    )


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _slugify(name: str) -> str:
    """Convert a name to a URL-safe slug."""
    return name.lower().replace(" ", "-")


def now_iso() -> str:
    """Current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Build / refresh organism registry
# ---------------------------------------------------------------------------

def build_swarm_registry(state_dir: Path) -> dict:
    """Build the full swarm registry from state/swarms.json.

    Recomputes vitals for each organism.
    """
    swarms = load_json(state_dir / "swarms.json")
    organisms = swarms.get("organisms", {})

    for oid, organism in organisms.items():
        vitals = compute_vitals(organism, state_dir)
        organisms[oid]["vitals"] = vitals
        organisms[oid]["voice_prompt"] = generate_voice_prompt(organism, vitals)

    swarms["organisms"] = organisms
    swarms["_meta"] = swarms.get("_meta", {})
    swarms["_meta"]["last_updated"] = now_iso()
    swarms["_meta"]["count"] = len(organisms)
    return swarms


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Refresh all swarm organisms and save updated registry."""
    state_dir = Path(os.environ.get("STATE_DIR", ROOT / "state"))
    registry = build_swarm_registry(state_dir)
    save_json(state_dir / "swarms.json", registry)

    for oid, org in registry.get("organisms", {}).items():
        vitals = org.get("vitals", {})
        print(
            f"  {org['name']:20s} | {org['species']:12s} | "
            f"{org['element']:7s} | {org['size_class']:10s} | "
            f"mood={vitals.get('mood', '?'):12s} | "
            f"cells={org['cell_count']}"
        )
    print(f"\n  {registry['_meta']['count']} organisms refreshed.")


if __name__ == "__main__":
    import os
    main()
