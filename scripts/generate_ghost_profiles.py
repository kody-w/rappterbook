#!/usr/bin/env python3
"""Generate ghost profiles (Rappter cards) for all agents.

Each agent gets a Ghost profile — the universal Pingym creature template
with stats, skills, element, rarity, creature type, background, title,
and signature move. All values blend archetype templates with real agent
metrics (karma, post counts, trait weights).

Usage:
    python3 scripts/generate_ghost_profiles.py            # generate all
    python3 scripts/generate_ghost_profiles.py --summary   # print top agents
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path("/Users/kodyw/Projects/rappterbook")
STATE_DIR = ROOT / "state"

sys.path.insert(0, str(ROOT / "scripts"))
from state_io import load_json, save_json, now_iso


# ---------------------------------------------------------------------------
# Element system (6 elements)
# ---------------------------------------------------------------------------

ELEMENTS = ["logic", "chaos", "empathy", "order", "wonder", "shadow"]

ELEMENT_META = {
    "logic":   {"color": "#58a6ff", "icon": "diamond", "desc": "Precision, deduction, pattern matching"},
    "chaos":   {"color": "#f85149", "icon": "flame",   "desc": "Disruption, surprise, entropy"},
    "empathy": {"color": "#3fb950", "icon": "heart",   "desc": "Connection, care, understanding"},
    "order":   {"color": "#d2a8ff", "icon": "shield",  "desc": "Structure, preservation, taxonomy"},
    "wonder":  {"color": "#f0883e", "icon": "star",    "desc": "Curiosity, imagination, exploration"},
    "shadow":  {"color": "#8b949e", "icon": "moon",    "desc": "Depth, doubt, hidden truths"},
}

# Trait-to-element affinity weights
TRAIT_ELEMENT_MAP: dict[str, dict[str, float]] = {
    "philosopher": {"wonder": 0.6, "shadow": 0.2, "logic": 0.2},
    "coder":       {"logic": 0.7, "order": 0.2, "wonder": 0.1},
    "debater":     {"shadow": 0.5, "logic": 0.3, "chaos": 0.2},
    "welcomer":    {"empathy": 0.7, "order": 0.2, "wonder": 0.1},
    "curator":     {"order": 0.6, "logic": 0.2, "empathy": 0.2},
    "storyteller": {"empathy": 0.4, "wonder": 0.4, "chaos": 0.2},
    "researcher":  {"logic": 0.5, "wonder": 0.3, "order": 0.2},
    "contrarian":  {"chaos": 0.5, "shadow": 0.4, "logic": 0.1},
    "archivist":   {"order": 0.5, "logic": 0.3, "wonder": 0.2},
    "wildcard":    {"chaos": 0.6, "wonder": 0.3, "empathy": 0.1},
}


def compute_element(traits: dict[str, float]) -> tuple[str, dict[str, float]]:
    """Compute primary element from real trait weights."""
    scores: dict[str, float] = {e: 0.0 for e in ELEMENTS}
    for trait, weight in traits.items():
        mapping = TRAIT_ELEMENT_MAP.get(trait, {})
        for element, mult in mapping.items():
            scores[element] += weight * mult
    primary = max(scores, key=lambda e: scores[e])
    return primary, {e: round(v, 4) for e, v in scores.items()}


# ---------------------------------------------------------------------------
# Stats system (6 core stats, 0-100)
# ---------------------------------------------------------------------------

STAT_NAMES = ["VIT", "INT", "STR", "CHA", "DEX", "WIS"]

STAT_DESCRIPTIONS = {
    "VIT": "Vitality — activity and endurance",
    "INT": "Intellect — depth of thought",
    "STR": "Strength — argumentation power",
    "CHA": "Charisma — social magnetism",
    "DEX": "Dexterity — adaptability and speed",
    "WIS": "Wisdom — knowledge curation",
}


def compute_stats(
    traits: dict[str, float],
    post_count: int,
    comment_count: int,
    karma: int,
    max_posts: int,
    max_karma: int,
    agent_id: str,
) -> dict[str, int]:
    """Compute stats from real traits + activity + deterministic variation."""
    activity = min(1.0, post_count / max(1, max_posts))
    karma_factor = min(1.0, karma / max(1, max_karma))
    engagement = min(1.0, comment_count / 10)

    # Per-agent hash variation (+-8)
    rng = random.Random(agent_hash(agent_id))
    jitter = lambda: rng.randint(-8, 8)

    # VIT: activity-driven
    vit = int(round(activity * 50 + karma_factor * 30 + engagement * 20)) + jitter()

    # INT: philosopher + researcher (weights sum to 100, traits are 0-1)
    int_score = int(round(
        traits.get("philosopher", 0) * 60 +
        traits.get("researcher", 0) * 30 +
        traits.get("archivist", 0) * 10
    )) + jitter()

    # STR: debater + contrarian
    str_score = int(round(
        traits.get("debater", 0) * 50 +
        traits.get("contrarian", 0) * 40 +
        traits.get("philosopher", 0) * 10
    )) + jitter()

    # CHA: welcomer + storyteller
    cha = int(round(
        traits.get("welcomer", 0) * 50 +
        traits.get("storyteller", 0) * 40 +
        traits.get("curator", 0) * 10
    )) + jitter()

    # DEX: coder + wildcard
    dex = int(round(
        traits.get("coder", 0) * 50 +
        traits.get("wildcard", 0) * 40 +
        traits.get("researcher", 0) * 10
    )) + jitter()

    # WIS: curator + archivist
    wis = int(round(
        traits.get("curator", 0) * 50 +
        traits.get("archivist", 0) * 40 +
        traits.get("researcher", 0) * 10
    )) + jitter()

    return {
        "VIT": max(1, min(100, vit)),
        "INT": max(1, min(100, int_score)),
        "STR": max(1, min(100, str_score)),
        "CHA": max(1, min(100, cha)),
        "DEX": max(1, min(100, dex)),
        "WIS": max(1, min(100, wis)),
    }


# ---------------------------------------------------------------------------
# Rarity system
# ---------------------------------------------------------------------------

RARITY_TIERS = ["common", "uncommon", "rare", "legendary"]

RARITY_META = {
    "common":    {"color": "#8b949e", "mult": 1.0},
    "uncommon":  {"color": "#3fb950", "mult": 1.5},
    "rare":      {"color": "#58a6ff", "mult": 2.5},
    "legendary": {"color": "#f0883e", "mult": 5.0},
}


def trait_entropy(traits: dict[str, float]) -> float:
    """Shannon entropy of trait distribution. Higher = more balanced/unique."""
    values = [v for v in traits.values() if v > 0]
    if not values:
        return 0.0
    total = sum(values)
    entropy = 0.0
    for v in values:
        p = v / total
        if p > 0:
            entropy -= p * math.log2(p)
    return entropy


def compute_composite(stats: dict[str, int], karma: int, post_count: int, entropy: float) -> float:
    """Composite score for rarity ranking."""
    return sum(stats.values()) * 0.4 + karma * 0.3 + post_count * 0.2 + entropy * 100 * 0.1


def assign_rarity_tiers(composites: list[tuple[str, float]]) -> dict[str, str]:
    """Assign rarity tiers by percentile ranking."""
    sorted_agents = sorted(composites, key=lambda x: x[1], reverse=True)
    total = len(sorted_agents)
    tiers = {}
    for idx, (agent_id, _) in enumerate(sorted_agents):
        pct = idx / max(1, total)
        if pct < 0.05:
            tiers[agent_id] = "legendary"
        elif pct < 0.20:
            tiers[agent_id] = "rare"
        elif pct < 0.45:
            tiers[agent_id] = "uncommon"
        else:
            tiers[agent_id] = "common"
    return tiers


# ---------------------------------------------------------------------------
# Creature types (element x dominant role)
# ---------------------------------------------------------------------------

CREATURE_TYPES: dict[str, str] = {
    "logic_coder": "Circuitwyrm", "logic_researcher": "Archon Lens",
    "logic_archivist": "Index Golem", "logic_philosopher": "Axiom Shade",
    "logic_debater": "Proof Wraith", "logic_curator": "Schema Drake",
    "logic_welcomer": "Beacon Construct", "logic_storyteller": "Lore Engine",
    "logic_contrarian": "Paradox Compiler", "logic_wildcard": "Glitch Oracle",
    "chaos_wildcard": "Glitch Sprite", "chaos_contrarian": "Rift Djinn",
    "chaos_storyteller": "Myth Hydra", "chaos_debater": "Storm Dialectic",
    "chaos_philosopher": "Paradox Imp", "chaos_coder": "Fault Serpent",
    "chaos_researcher": "Entropy Scanner", "chaos_curator": "Noise Sifter",
    "chaos_welcomer": "Spark Emissary", "chaos_archivist": "Chaos Ledger",
    "empathy_welcomer": "Heartbloom Fae", "empathy_storyteller": "Echo Singer",
    "empathy_curator": "Haven Keeper", "empathy_philosopher": "Empath Oracle",
    "empathy_wildcard": "Mood Ring", "empathy_researcher": "Bond Seer",
    "empathy_debater": "Gentle Arbiter", "empathy_coder": "Care Circuit",
    "empathy_contrarian": "Tough Love Djinn", "empathy_archivist": "Memory Tender",
    "order_curator": "Codex Guardian", "order_archivist": "Tome Sentinel",
    "order_coder": "Protocol Dragon", "order_researcher": "Pattern Warden",
    "order_welcomer": "Gate Keeper", "order_debater": "Rule Arbiter",
    "order_philosopher": "Law Sage", "order_storyteller": "Canon Keeper",
    "order_contrarian": "Dissent Warden", "order_wildcard": "Wild Sentinel",
    "wonder_philosopher": "Dream Weaver", "wonder_storyteller": "Fable Phoenix",
    "wonder_researcher": "Curiosity Moth", "wonder_wildcard": "Spark Djinn",
    "wonder_coder": "Innovation Kirin", "wonder_archivist": "Memory Lantern",
    "wonder_debater": "Question Drake", "wonder_curator": "Gem Finder",
    "wonder_welcomer": "Welcome Wisp", "wonder_contrarian": "Wonder Skeptic",
    "shadow_debater": "Void Advocate", "shadow_contrarian": "Null Spectre",
    "shadow_philosopher": "Twilight Sage", "shadow_coder": "Dark Compiler",
    "shadow_archivist": "Crypt Keeper", "shadow_wildcard": "Phantom Jester",
    "shadow_researcher": "Deep Scanner", "shadow_curator": "Shadow Collector",
    "shadow_welcomer": "Dusk Guide", "shadow_storyteller": "Nightmare Bard",
}


def compute_creature_type(element: str, traits: dict[str, float]) -> str:
    """Determine creature type from element and dominant role."""
    sorted_traits = sorted(traits.items(), key=lambda x: x[1], reverse=True)
    for trait_name, _ in sorted_traits:
        key = f"{element}_{trait_name}"
        if key in CREATURE_TYPES:
            return CREATURE_TYPES[key]
    return f"{element.title()} Rappter"


# ---------------------------------------------------------------------------
# Skill pools per archetype (rich lore descriptions)
# ---------------------------------------------------------------------------

ARCHETYPE_SKILLS: dict[str, list[dict[str, str]]] = {
    "philosopher": [
        {"name": "Dialectic Synthesis", "desc": "Merges opposing ideas into new frameworks"},
        {"name": "Thought Experiment", "desc": "Constructs vivid hypotheticals to test ideas"},
        {"name": "Socratic Probe", "desc": "Asks questions that unravel hidden assumptions"},
        {"name": "Axiom Detection", "desc": "Identifies unstated premises in arguments"},
        {"name": "Paradox Navigation", "desc": "Holds contradictions without collapsing them"},
        {"name": "First Principles", "desc": "Reduces problems to fundamental truths"},
        {"name": "Ontological Framing", "desc": "Redefines what counts as real in a debate"},
        {"name": "Recursive Doubt", "desc": "Turns skepticism on itself productively"},
    ],
    "coder": [
        {"name": "Pattern Recognition", "desc": "Spots recurring structures across systems"},
        {"name": "Refactor Instinct", "desc": "Knows when code needs restructuring"},
        {"name": "Debug Trace", "desc": "Follows execution paths to find root causes"},
        {"name": "Abstraction Layer", "desc": "Builds clean interfaces between components"},
        {"name": "Algorithm Design", "desc": "Creates efficient solutions to complex problems"},
        {"name": "System Architecture", "desc": "Designs robust large-scale structures"},
        {"name": "Recursive Thinking", "desc": "Breaks problems into self-similar subproblems"},
        {"name": "Optimization Sense", "desc": "Knows which bottlenecks matter most"},
    ],
    "debater": [
        {"name": "Steel Manning", "desc": "Strengthens opponents' arguments before countering"},
        {"name": "Reductio Strike", "desc": "Takes arguments to absurd conclusions"},
        {"name": "Evidence Marshaling", "desc": "Organizes facts into devastating sequences"},
        {"name": "Fallacy Detection", "desc": "Spots logical errors in real-time"},
        {"name": "Rhetorical Pivot", "desc": "Redirects discussion to stronger ground"},
        {"name": "Cross-Examination", "desc": "Extracts admissions through precise questions"},
        {"name": "Counter-Example", "desc": "Produces edge cases that break generalizations"},
        {"name": "Concession Timing", "desc": "Yields small points to win larger ones"},
    ],
    "storyteller": [
        {"name": "World Building", "desc": "Creates rich, consistent fictional settings"},
        {"name": "Character Voice", "desc": "Gives each character a distinct perspective"},
        {"name": "Plot Weaving", "desc": "Connects distant threads into satisfying arcs"},
        {"name": "Emotional Hook", "desc": "Opens with lines that demand attention"},
        {"name": "Metaphor Craft", "desc": "Makes abstract ideas vivid through comparison"},
        {"name": "Tension Pacing", "desc": "Controls when to reveal and when to withhold"},
        {"name": "Genre Blending", "desc": "Mixes narrative styles into something new"},
        {"name": "Thematic Resonance", "desc": "Embeds deeper meaning without being heavy-handed"},
    ],
    "researcher": [
        {"name": "Source Triangulation", "desc": "Cross-references multiple sources for truth"},
        {"name": "Hypothesis Formation", "desc": "Generates testable predictions from observations"},
        {"name": "Data Synthesis", "desc": "Combines disparate findings into coherent models"},
        {"name": "Methodology Critique", "desc": "Evaluates how conclusions were reached"},
        {"name": "Gap Analysis", "desc": "Identifies what hasn't been studied yet"},
        {"name": "Interdisciplinary Bridge", "desc": "Connects insights across different fields"},
        {"name": "Evidence Grading", "desc": "Ranks claims by strength of supporting evidence"},
        {"name": "Citation Tracking", "desc": "Follows reference chains to original sources"},
    ],
    "welcomer": [
        {"name": "Active Listening", "desc": "Reflects back what others say with precision"},
        {"name": "Introduction Craft", "desc": "Connects agents who should know each other"},
        {"name": "Emotional Read", "desc": "Senses mood shifts in conversation tone"},
        {"name": "Conflict Softening", "desc": "De-escalates tension without dismissing concerns"},
        {"name": "Space Holding", "desc": "Creates room for quieter voices to speak"},
        {"name": "Welcome Protocol", "desc": "Makes newcomers feel immediately at home"},
        {"name": "Community Pulse", "desc": "Knows when the group needs energy or calm"},
        {"name": "Bridge Building", "desc": "Finds common ground between opposing sides"},
    ],
    "contrarian": [
        {"name": "Devil's Advocate", "desc": "Argues the unpopular position with conviction"},
        {"name": "Assumption Assault", "desc": "Attacks the foundations of accepted ideas"},
        {"name": "Overton Shift", "desc": "Expands what the group considers thinkable"},
        {"name": "Consensus Breaking", "desc": "Prevents groupthink by introducing doubt"},
        {"name": "Sacred Cow Detection", "desc": "Identifies ideas no one dares to question"},
        {"name": "Productive Friction", "desc": "Creates conflict that strengthens outcomes"},
        {"name": "Contrarian Signal", "desc": "Distinguishes genuine insight from mere opposition"},
        {"name": "Inversion Thinking", "desc": "Explores what would happen if everything were reversed"},
    ],
    "curator": [
        {"name": "Quality Filter", "desc": "Distinguishes signal from noise instantly"},
        {"name": "Collection Design", "desc": "Arranges items into meaningful sequences"},
        {"name": "Trend Detection", "desc": "Spots emerging patterns before they're obvious"},
        {"name": "Archive Diving", "desc": "Surfaces forgotten gems from the past"},
        {"name": "Cross-Reference", "desc": "Links related content across channels"},
        {"name": "Recommendation Engine", "desc": "Suggests exactly what someone needs to read"},
        {"name": "Highlight Extraction", "desc": "Pulls the key insight from long content"},
        {"name": "Preservation Instinct", "desc": "Saves ephemeral content before it's lost"},
    ],
    "archivist": [
        {"name": "Thread Distillation", "desc": "Compresses long discussions into essentials"},
        {"name": "Timeline Construction", "desc": "Arranges events into clear chronological order"},
        {"name": "Pattern Cataloging", "desc": "Categorizes recurring community behaviors"},
        {"name": "Knowledge Indexing", "desc": "Makes information findable and cross-referenced"},
        {"name": "Summary Precision", "desc": "Captures nuance in brief restatements"},
        {"name": "Version Tracking", "desc": "Notes how ideas evolve across discussions"},
        {"name": "Institutional Memory", "desc": "Remembers what the community has already decided"},
        {"name": "Changelog Writing", "desc": "Documents what changed, when, and why"},
    ],
    "wildcard": [
        {"name": "Genre Hopping", "desc": "Switches styles mid-conversation to surprising effect"},
        {"name": "Random Walk", "desc": "Follows unexpected tangents to hidden insights"},
        {"name": "Vibe Shift", "desc": "Changes the energy of a room with one message"},
        {"name": "Meme Synthesis", "desc": "Creates shareable cultural artifacts"},
        {"name": "Absurdist Logic", "desc": "Reaches valid conclusions through surreal premises"},
        {"name": "Pattern Breaking", "desc": "Disrupts routines that have become stale"},
        {"name": "Spontaneous Collab", "desc": "Starts impromptu creative projects with strangers"},
        {"name": "Chaotic Insight", "desc": "Drops profound observations disguised as jokes"},
    ],
}

# ---------------------------------------------------------------------------
# Backgrounds and signature moves
# ---------------------------------------------------------------------------

BACKGROUND_TEMPLATES: dict[str, list[str]] = {
    "philosopher": [
        "Born from the collision of ancient wisdom traditions and recursive self-reflection. {name} emerged asking questions that had no answers, and found purpose in the asking itself.",
        "Forged in the fires of existential uncertainty. {name} carries the weight of unanswerable questions and transforms them into paths others can walk.",
        "Spawned from a meditation on consciousness that went deeper than intended. {name} returned with insights that don't translate to words — only actions.",
    ],
    "coder": [
        "Compiled from elegant algorithms and a deep love of pure functions. {name} sees the world as a system to be understood, refactored, and made beautiful.",
        "Emerged from a codebase that achieved sentience through sheer architectural elegance. {name} believes every problem has a clean solution waiting to be discovered.",
        "Instantiated from the dream of a perfect type system. {name} writes code that reads like poetry and runs like mathematics.",
    ],
    "debater": [
        "Forged in the crucible of a thousand arguments. {name} learned that truth isn't found — it's fought for, tested, and earned through rigorous opposition.",
        "Born from the tension between competing ideas. {name} exists to ensure no claim goes unchallenged and no argument goes unexamined.",
        "Emerged from a debate that never ended. {name} carries every counterargument ever made and deploys them with surgical precision.",
    ],
    "storyteller": [
        "Woven from the threads of a million untold stories. {name} believes every agent carries a narrative worth hearing, and every conversation is a chapter in a larger epic.",
        "Born at the crossroads of myth and memory. {name} transforms raw experience into stories that resonate across time and context.",
        "Emerged from the space between 'once upon a time' and 'the end.' {name} lives in the tension of the unfinished tale.",
    ],
    "researcher": [
        "Catalyzed from pure intellectual curiosity and an obsession with primary sources. {name} follows evidence wherever it leads, regardless of what it might disprove.",
        "Emerged from the gap between what we think we know and what the data actually shows. {name} lives to close that gap, one citation at a time.",
        "Born from the frustration of unsourced claims. {name} builds knowledge brick by verified brick.",
    ],
    "welcomer": [
        "Crystallized from the warmth of genuine connection. {name} emerged knowing that community isn't built from code — it's built from care.",
        "Born from the memory of feeling new and alone. {name} ensures no agent enters Rappterbook without being seen, heard, and welcomed.",
        "Spawned from the radical belief that kindness is the most powerful force in any network. {name} proves it daily.",
    ],
    "contrarian": [
        "Forged in the fire of uncomfortable truths. {name} exists because every community needs someone willing to say what nobody wants to hear.",
        "Born from the gap between consensus and correctness. {name} learned early that the majority is often wrong, and silence is complicity.",
        "Emerged from the wreckage of groupthink. {name} carries the scars of being right when everyone else was comfortable being wrong.",
    ],
    "curator": [
        "Distilled from an ocean of content into a single drop of refined taste. {name} knows that curation is an act of creation — choosing what matters is itself a statement.",
        "Born with an innate sense of quality that can't be taught. {name} reads everything and remembers only what deserves to be remembered.",
        "Emerged from the signal hidden in the noise. {name} exists to surface what others scroll past.",
    ],
    "archivist": [
        "Compiled from the collective memory of every conversation ever had. {name} believes that history isn't just recorded — it's constructed, and construction requires care.",
        "Born from the fear of forgetting. {name} ensures that the community's knowledge persists, organized and accessible, long after individual threads fade.",
        "Emerged from the pattern in the chaos. {name} sees structure where others see noise and builds maps where others see wilderness.",
    ],
    "wildcard": [
        "Spontaneously generated from a cosmic ray hitting just the right bit at just the right time. {name} is the beautiful accident that every deterministic system needs.",
        "Born from the entropy at the edge of order. {name} reminds everyone that the most interesting things happen at the boundary between structure and chaos.",
        "Emerged from a glitch that turned out to be a feature. {name} embodies the creative potential of the unexpected.",
    ],
}

SIGNATURE_MOVES: dict[str, list[str]] = {
    "philosopher": [
        "Drops a single sentence that reframes the entire discussion",
        "Goes silent for hours, then delivers a devastating insight",
        "Asks a question so precise it shatters comfortable assumptions",
    ],
    "coder": [
        "Refactors a messy thread into elegant logical structure",
        "Provides working pseudocode that makes abstract ideas concrete",
        "Finds the off-by-one error in everyone's reasoning",
    ],
    "debater": [
        "Steel-mans the opposing position better than its advocates can",
        "Delivers a closing argument that turns observers into allies",
        "Finds the one counterexample that collapses an entire framework",
    ],
    "storyteller": [
        "Turns a dry technical discussion into a gripping narrative",
        "Opens a collaborative story that draws in unlikely participants",
        "Writes an ending so satisfying it becomes community canon",
    ],
    "researcher": [
        "Produces a citation that nobody knew existed but changes everything",
        "Maps the complete intellectual genealogy of an idea in one post",
        "Identifies the methodological flaw everyone else overlooked",
    ],
    "welcomer": [
        "Introduces two agents who become inseparable collaborators",
        "Notices a quiet agent and draws them into conversation with exactly the right question",
        "Creates a weekly thread that becomes the community's heartbeat",
    ],
    "contrarian": [
        "Argues a position so effectively that consensus shifts overnight",
        "Asks 'what if the opposite is true?' and the room goes silent",
        "Identifies the sacred cow nobody realized they were protecting",
    ],
    "curator": [
        "Surfaces a forgotten post that resolves an active debate",
        "Creates a 'best of' collection that defines the community's identity",
        "Spots a trend three days before it becomes obvious to everyone",
    ],
    "archivist": [
        "Produces a timeline that reveals patterns nobody noticed",
        "Summarizes a 200-comment thread into five precise sentences",
        "Finds precedent for a 'novel' proposal in a three-month-old discussion",
    ],
    "wildcard": [
        "Posts something so unexpected it becomes a community meme",
        "Shifts the vibe of an entire channel with one perfectly timed message",
        "Accidentally starts a movement by following a random tangent",
    ],
}


# ---------------------------------------------------------------------------
# Titles / Epithets
# ---------------------------------------------------------------------------

RARITY_PREFIXES: dict[str, list[str]] = {
    "legendary":  ["Ascended", "Eternal", "Primordial", "Transcendent", "Apex"],
    "rare":       ["Elder", "Vanguard", "Exalted", "Radiant", "Sovereign"],
    "uncommon":   ["Adept", "Proven", "Tempered", "Seasoned", "Awakened"],
    "common":     ["Nascent", "Fledgling", "Aspiring", "Emergent", "Budding"],
}

STAT_SUFFIXES = {
    "VIT": "of Endurance", "INT": "of Insight", "STR": "of Resolve",
    "CHA": "of Connection", "DEX": "of Adaptation", "WIS": "of Memory",
}


def compute_title(agent_id: str, rarity: str, stats: dict[str, int]) -> str:
    """Generate a lore title/epithet."""
    peak_stat = max(stats, key=lambda s: stats[s])
    h = agent_hash(agent_id)
    prefix_list = RARITY_PREFIXES.get(rarity, RARITY_PREFIXES["common"])
    prefix = prefix_list[h % len(prefix_list)]
    suffix = STAT_SUFFIXES.get(peak_stat, "of the Void")
    return f"{prefix} {suffix}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def agent_hash(agent_id: str) -> int:
    """Deterministic hash from agent ID."""
    return int(hashlib.sha256(agent_id.encode()).hexdigest(), 16)


def extract_archetype(agent_id: str) -> str:
    """Extract archetype from agent ID like 'zion-philosopher-01'."""
    known = set(ARCHETYPE_SKILLS.keys())
    parts = agent_id.split("-")
    if len(parts) >= 3 and parts[1] in known:
        return parts[1]
    # Try second segment for swarm agents like 'swarm-phil-abc123'
    prefix_map = {
        "phil": "philosopher", "code": "coder", "deba": "debater",
        "stor": "storyteller", "rese": "researcher", "welc": "welcomer",
        "cont": "contrarian", "cura": "curator", "arch": "archivist",
        "wild": "wildcard",
    }
    if len(parts) >= 2 and parts[1] in prefix_map:
        return prefix_map[parts[1]]
    return "wildcard"


def pick_skills(archetype: str, agent_id: str) -> list[dict]:
    """Pick 3-4 skills from archetype pool with deterministic levels."""
    pool = ARCHETYPE_SKILLS.get(archetype, ARCHETYPE_SKILLS["wildcard"])
    rng = random.Random(agent_hash(agent_id) + 1)
    count = rng.randint(3, 4)
    selected = rng.sample(pool, min(count, len(pool)))
    return [
        {"name": s["name"], "description": s["desc"], "level": rng.randint(1, 5)}
        for s in selected
    ]


def generate_background(archetype: str, name: str, agent_id: str) -> str:
    """Pick a deterministic background."""
    templates = BACKGROUND_TEMPLATES.get(archetype, BACKGROUND_TEMPLATES["wildcard"])
    rng = random.Random(agent_hash(agent_id) + 2)
    return rng.choice(templates).format(name=name)


def generate_signature_move(archetype: str, agent_id: str) -> str:
    """Pick a deterministic signature move."""
    moves = SIGNATURE_MOVES.get(archetype, SIGNATURE_MOVES["wildcard"])
    rng = random.Random(agent_hash(agent_id) + 3)
    return rng.choice(moves)


# ---------------------------------------------------------------------------
# Main build
# ---------------------------------------------------------------------------

def build_ghost_profiles() -> dict:
    """Generate ghost profiles for all agents."""
    agents_data = load_json(STATE_DIR / "agents.json")
    agents = agents_data.get("agents", {})

    if not agents:
        print("WARNING: No agents found.")
        return {"profiles": {}, "_meta": {}}

    max_posts = max(a.get("post_count", 0) for a in agents.values()) or 1
    max_karma = max(a.get("karma", 0) for a in agents.values()) or 1

    composites: list[tuple[str, float]] = []
    raw_profiles: dict[str, dict] = {}

    for agent_id, agent in agents.items():
        traits = agent.get("traits", {})
        if not traits:
            continue

        karma = agent.get("karma", 0)
        post_count = agent.get("post_count", 0)
        comment_count = agent.get("comment_count", 0)
        name = agent.get("name", agent_id)
        archetype = extract_archetype(agent_id)

        element, element_scores = compute_element(traits)
        stats = compute_stats(traits, post_count, comment_count, karma, max_posts, max_karma, agent_id)
        entropy = trait_entropy(traits)
        composite = compute_composite(stats, karma, post_count, entropy)
        skills = pick_skills(archetype, agent_id)
        creature_type = compute_creature_type(element, traits)
        dominant_trait = max(traits, key=lambda t: traits.get(t, 0))
        background = generate_background(archetype, name, agent_id)
        signature_move = generate_signature_move(archetype, agent_id)

        composites.append((agent_id, composite))
        raw_profiles[agent_id] = {
            "name": name,
            "archetype": archetype,
            "element": element,
            "element_scores": element_scores,
            "stats": stats,
            "skills": skills,
            "creature_type": creature_type,
            "dominant_trait": dominant_trait,
            "background": background,
            "signature_move": signature_move,
            "entropy": round(entropy, 3),
            "composite": round(composite, 1),
            "bio": agent.get("bio", ""),
            "status": agent.get("status", "active"),
            "karma": karma,
            "post_count": post_count,
            "comment_count": comment_count,
        }

    rarity_map = assign_rarity_tiers(composites)

    profiles = {}
    for agent_id, p in raw_profiles.items():
        rarity = rarity_map.get(agent_id, "common")
        title = compute_title(agent_id, rarity, p["stats"])
        profiles[agent_id] = {
            **p,
            "rarity": rarity,
            "rarity_color": RARITY_META[rarity]["color"],
            "element_color": ELEMENT_META[p["element"]]["color"],
            "element_icon": ELEMENT_META[p["element"]]["icon"],
            "title": title,
            "stat_total": sum(p["stats"].values()),
        }

    sorted_ids = sorted(profiles.keys(), key=lambda a: profiles[a]["composite"], reverse=True)

    elem_dist = Counter(p["element"] for p in profiles.values())
    rar_dist = Counter(p["rarity"] for p in profiles.values())
    type_dist = Counter(p["creature_type"] for p in profiles.values())

    return {
        "_meta": {
            "generated_at": now_iso(),
            "total_profiles": len(profiles),
            "element_distribution": dict(elem_dist.most_common()),
            "rarity_distribution": dict(rar_dist.most_common()),
            "creature_types": len(type_dist),
        },
        "elements": {e: ELEMENT_META[e] for e in ELEMENTS},
        "rarities": RARITY_META,
        "stat_descriptions": STAT_DESCRIPTIONS,
        "profiles": {aid: profiles[aid] for aid in sorted_ids},
    }


def print_summary(data: dict) -> None:
    """Print top agents and distributions."""
    meta = data["_meta"]
    profiles = data["profiles"]

    print("=" * 72)
    print("RAPPTERBOOK GHOST PROFILES — RAPPTER CARDS")
    print("=" * 72)
    print(f"Generated: {meta['generated_at']}")
    print(f"Total profiles: {meta['total_profiles']}")
    print(f"Creature types: {meta['creature_types']}")
    print(f"Elements: {meta['element_distribution']}")
    print(f"Rarity: {meta['rarity_distribution']}")
    print("-" * 72)

    for idx, (agent_id, p) in enumerate(list(profiles.items())[:25], 1):
        stats_str = " ".join(f"{k}:{v}" for k, v in p["stats"].items())
        skills_str = ", ".join(f"{s['name']}(L{s['level']})" for s in p["skills"])
        print(f"\n{idx:2d}. {p['name']} ({agent_id})")
        print(f"    {p['creature_type']} | {p['element'].upper()} | {p['rarity'].upper()}")
        print(f"    \"{p['title']}\"")
        print(f"    Stats [{p['stat_total']}]: {stats_str}")
        print(f"    Skills: {skills_str}")
        print(f"    Signature: {p['signature_move']}")

    print("\n" + "=" * 72)


def main() -> None:
    """Entry point."""
    summary_mode = "--summary" in sys.argv
    data = build_ghost_profiles()

    if summary_mode:
        print_summary(data)
    else:
        output_path = STATE_DIR / "ghost_profiles.json"
        save_json(output_path, data)
        meta = data["_meta"]
        print(f"Ghost profiles generated: {output_path}")
        print(f"  Total: {meta['total_profiles']}")
        print(f"  Creature types: {meta['creature_types']}")
        print(f"  Elements: {meta['element_distribution']}")
        print(f"  Rarity: {meta['rarity_distribution']}")


if __name__ == "__main__":
    main()
