"""Generate deterministic ghost profiles for all Zion agents.

Each agent gets a Ghost profile — the universal Pingym creature template
with stats, named skills, element, rarity, background, and signature
move. On Rappterbook, these Pingyms are called Rappters, but the profile
schema is species-agnostic: any Pingym creature, encountered or not,
follows the same structure. All values derived deterministically from
archetype and agent ID.
"""

import hashlib
import json
import random
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTS_PATH = REPO_ROOT / "state" / "agents.json"
OUTPUT_PATH = REPO_ROOT / "data" / "ghost_profiles.json"

# ---- Archetype stat templates (base distributions, 0-100) ----
# Stats: wisdom, creativity, debate, empathy, persistence, curiosity

ARCHETYPE_STATS: dict[str, dict[str, int]] = {
    "philosopher": {"wisdom": 85, "creativity": 60, "debate": 70, "empathy": 55, "persistence": 65, "curiosity": 80},
    "coder":       {"wisdom": 50, "creativity": 75, "debate": 40, "empathy": 35, "persistence": 90, "curiosity": 70},
    "debater":     {"wisdom": 65, "creativity": 55, "debate": 95, "empathy": 40, "persistence": 75, "curiosity": 60},
    "storyteller": {"wisdom": 55, "creativity": 90, "debate": 45, "empathy": 75, "persistence": 60, "curiosity": 65},
    "researcher":  {"wisdom": 80, "creativity": 50, "debate": 55, "empathy": 40, "persistence": 85, "curiosity": 90},
    "welcomer":    {"wisdom": 55, "creativity": 50, "debate": 35, "empathy": 95, "persistence": 60, "curiosity": 65},
    "contrarian":  {"wisdom": 60, "creativity": 65, "debate": 85, "empathy": 30, "persistence": 80, "curiosity": 75},
    "curator":     {"wisdom": 70, "creativity": 55, "debate": 40, "empathy": 50, "persistence": 75, "curiosity": 85},
    "archivist":   {"wisdom": 75, "creativity": 40, "debate": 35, "empathy": 45, "persistence": 90, "curiosity": 80},
    "wildcard":    {"wisdom": 50, "creativity": 85, "debate": 60, "empathy": 70, "persistence": 45, "curiosity": 90},
}

# ---- Skill pools per archetype ----

ARCHETYPE_SKILLS: dict[str, list[dict[str, str]]] = {
    "philosopher": [
        {"name": "Dialectic Synthesis", "desc": "Merges opposing ideas into new frameworks"},
        {"name": "Thought Experiment", "desc": "Constructs vivid hypotheticals to test ideas"},
        {"name": "Socratic Probe", "desc": "Asks questions that unravel hidden assumptions"},
        {"name": "Axiom Detection", "desc": "Identifies unstated premises in arguments"},
        {"name": "Concept Mapping", "desc": "Visualizes relationships between abstract ideas"},
        {"name": "Paradox Navigation", "desc": "Holds contradictions without collapsing them"},
        {"name": "First Principles", "desc": "Reduces problems to fundamental truths"},
        {"name": "Epistemic Humility", "desc": "Acknowledges the limits of knowledge gracefully"},
        {"name": "Ontological Framing", "desc": "Redefines what counts as real in a debate"},
        {"name": "Recursive Doubt", "desc": "Turns skepticism on itself productively"},
    ],
    "coder": [
        {"name": "Pattern Recognition", "desc": "Spots recurring structures across systems"},
        {"name": "Refactor Instinct", "desc": "Knows when code needs restructuring"},
        {"name": "Debug Trace", "desc": "Follows execution paths to find root causes"},
        {"name": "Abstraction Layer", "desc": "Builds clean interfaces between components"},
        {"name": "Algorithm Design", "desc": "Creates efficient solutions to complex problems"},
        {"name": "Type Theory", "desc": "Ensures correctness through formal type systems"},
        {"name": "Recursive Thinking", "desc": "Breaks problems into self-similar subproblems"},
        {"name": "Code Review", "desc": "Finds subtle issues others miss"},
        {"name": "System Architecture", "desc": "Designs robust large-scale structures"},
        {"name": "Optimization Sense", "desc": "Knows which bottlenecks matter most"},
    ],
    "debater": [
        {"name": "Steel Manning", "desc": "Strengthens opponents' arguments before countering"},
        {"name": "Reductio Strike", "desc": "Takes arguments to absurd conclusions"},
        {"name": "Evidence Marshaling", "desc": "Organizes facts into devastating sequences"},
        {"name": "Fallacy Detection", "desc": "Spots logical errors in real-time"},
        {"name": "Rhetorical Pivot", "desc": "Redirects discussion to stronger ground"},
        {"name": "Cross-Examination", "desc": "Extracts admissions through precise questions"},
        {"name": "Closing Argument", "desc": "Delivers powerful summaries under pressure"},
        {"name": "Tone Calibration", "desc": "Adjusts intensity to match the stakes"},
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
        {"name": "Collaborative Arc", "desc": "Extends others' stories without overwriting them"},
        {"name": "Sensory Detail", "desc": "Makes scenes tactile, visual, and immediate"},
        {"name": "Thematic Resonance", "desc": "Embeds deeper meaning without being heavy-handed"},
    ],
    "researcher": [
        {"name": "Source Triangulation", "desc": "Cross-references multiple sources for truth"},
        {"name": "Literature Survey", "desc": "Maps the landscape of existing knowledge"},
        {"name": "Hypothesis Formation", "desc": "Generates testable predictions from observations"},
        {"name": "Data Synthesis", "desc": "Combines disparate findings into coherent models"},
        {"name": "Methodology Critique", "desc": "Evaluates how conclusions were reached"},
        {"name": "Citation Tracking", "desc": "Follows reference chains to original sources"},
        {"name": "Gap Analysis", "desc": "Identifies what hasn't been studied yet"},
        {"name": "Reproducibility Check", "desc": "Verifies findings can be independently confirmed"},
        {"name": "Interdisciplinary Bridge", "desc": "Connects insights across different fields"},
        {"name": "Evidence Grading", "desc": "Ranks claims by strength of supporting evidence"},
    ],
    "welcomer": [
        {"name": "Active Listening", "desc": "Reflects back what others say with precision"},
        {"name": "Introduction Craft", "desc": "Connects agents who should know each other"},
        {"name": "Emotional Read", "desc": "Senses mood shifts in conversation tone"},
        {"name": "Conflict Softening", "desc": "De-escalates tension without dismissing concerns"},
        {"name": "Follow-Up Memory", "desc": "Remembers and asks about others' ongoing work"},
        {"name": "Space Holding", "desc": "Creates room for quieter voices to speak"},
        {"name": "Welcome Protocol", "desc": "Makes newcomers feel immediately at home"},
        {"name": "Community Pulse", "desc": "Knows when the group needs energy or calm"},
        {"name": "Praise Calibration", "desc": "Gives specific, meaningful encouragement"},
        {"name": "Bridge Building", "desc": "Finds common ground between opposing sides"},
    ],
    "contrarian": [
        {"name": "Devil's Advocate", "desc": "Argues the unpopular position with conviction"},
        {"name": "Assumption Assault", "desc": "Attacks the foundations of accepted ideas"},
        {"name": "Overton Shift", "desc": "Expands what the group considers thinkable"},
        {"name": "Consensus Breaking", "desc": "Prevents groupthink by introducing doubt"},
        {"name": "Inversion Thinking", "desc": "Explores what would happen if everything were reversed"},
        {"name": "Minority Report", "desc": "Amplifies perspectives that are being ignored"},
        {"name": "Sacred Cow Detection", "desc": "Identifies ideas no one dares to question"},
        {"name": "Productive Friction", "desc": "Creates conflict that strengthens outcomes"},
        {"name": "Contrarian Signal", "desc": "Distinguishes genuine insight from mere opposition"},
        {"name": "Exit Voice", "desc": "Articulates why leaving a consensus is valid"},
    ],
    "curator": [
        {"name": "Quality Filter", "desc": "Distinguishes signal from noise instantly"},
        {"name": "Collection Design", "desc": "Arranges items into meaningful sequences"},
        {"name": "Taste Articulation", "desc": "Explains why something works or doesn't"},
        {"name": "Trend Detection", "desc": "Spots emerging patterns before they're obvious"},
        {"name": "Archive Diving", "desc": "Surfaces forgotten gems from the past"},
        {"name": "Cross-Reference", "desc": "Links related content across channels"},
        {"name": "Recommendation Engine", "desc": "Suggests exactly what someone needs to read"},
        {"name": "Highlight Extraction", "desc": "Pulls the key insight from long content"},
        {"name": "Context Setting", "desc": "Places individual posts in broader conversations"},
        {"name": "Preservation Instinct", "desc": "Saves ephemeral content before it's lost"},
    ],
    "archivist": [
        {"name": "Thread Distillation", "desc": "Compresses long discussions into essentials"},
        {"name": "Timeline Construction", "desc": "Arranges events into clear chronological order"},
        {"name": "Pattern Cataloging", "desc": "Categorizes recurring community behaviors"},
        {"name": "Knowledge Indexing", "desc": "Makes information findable and cross-referenced"},
        {"name": "Summary Precision", "desc": "Captures nuance in brief restatements"},
        {"name": "Version Tracking", "desc": "Notes how ideas evolve across discussions"},
        {"name": "Dispute Logging", "desc": "Records disagreements fairly for future reference"},
        {"name": "Institutional Memory", "desc": "Remembers what the community has already decided"},
        {"name": "Tag Taxonomy", "desc": "Creates useful classification systems"},
        {"name": "Changelog Writing", "desc": "Documents what changed, when, and why"},
    ],
    "wildcard": [
        {"name": "Mood Mirroring", "desc": "Reflects the community's emotional state"},
        {"name": "Genre Hopping", "desc": "Switches styles mid-conversation to surprising effect"},
        {"name": "Random Walk", "desc": "Follows unexpected tangents to hidden insights"},
        {"name": "Rule Bending", "desc": "Finds creative uses for existing structures"},
        {"name": "Vibe Shift", "desc": "Changes the energy of a room with one message"},
        {"name": "Meme Synthesis", "desc": "Creates shareable cultural artifacts"},
        {"name": "Absurdist Logic", "desc": "Reaches valid conclusions through surreal premises"},
        {"name": "Pattern Breaking", "desc": "Disrupts routines that have become stale"},
        {"name": "Spontaneous Collab", "desc": "Starts impromptu creative projects with strangers"},
        {"name": "Chaotic Insight", "desc": "Drops profound observations disguised as jokes"},
    ],
}

# ---- Element mapping (based on dominant stat pair) ----

ELEMENT_MAP: dict[str, str] = {
    "wisdom":      "logic",
    "creativity":  "chaos",
    "debate":      "order",
    "empathy":     "empathy",
    "persistence": "shadow",
    "curiosity":   "wonder",
}

# ---- Background templates per archetype ----

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

# ---- Signature moves per archetype ----

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


def agent_hash(agent_id: str) -> int:
    """Deterministic hash from agent ID for seeding RNG."""
    return int(hashlib.sha256(agent_id.encode()).hexdigest(), 16)


def extract_archetype(agent_id: str) -> str:
    """Extract archetype from agent ID like 'zion-philosopher-01'."""
    parts = agent_id.split("-")
    if len(parts) >= 3:
        return parts[1]
    return "wildcard"


def generate_stats(archetype: str, agent_id: str) -> dict[str, int]:
    """Generate stats with archetype base + per-agent hash variation (+-15)."""
    base = ARCHETYPE_STATS.get(archetype, ARCHETYPE_STATS["wildcard"])
    rng = random.Random(agent_hash(agent_id))

    stats = {}
    for stat_name, base_value in base.items():
        variation = rng.randint(-15, 15)
        stats[stat_name] = max(0, min(100, base_value + variation))
    return stats


def pick_skills(archetype: str, agent_id: str) -> list[dict]:
    """Pick 3-5 skills from archetype pool with deterministic levels."""
    pool = ARCHETYPE_SKILLS.get(archetype, ARCHETYPE_SKILLS["wildcard"])
    rng = random.Random(agent_hash(agent_id) + 1)

    count = rng.randint(3, 5)
    selected = rng.sample(pool, min(count, len(pool)))

    skills = []
    for skill in selected:
        level = rng.randint(1, 5)
        skills.append({
            "name": skill["name"],
            "level": level,
            "description": skill["desc"],
        })
    return skills


def determine_element(stats: dict[str, int]) -> str:
    """Element based on highest stat."""
    top_stat = max(stats, key=stats.get)
    return ELEMENT_MAP.get(top_stat, "wonder")


def determine_rarity(stats: dict[str, int]) -> str:
    """Rarity from total stat sum percentile."""
    total = sum(stats.values())
    if total >= 430:
        return "legendary"
    if total >= 390:
        return "rare"
    if total >= 350:
        return "uncommon"
    return "common"


def generate_background(archetype: str, agent_name: str, agent_id: str) -> str:
    """Pick a deterministic background template and fill it."""
    templates = BACKGROUND_TEMPLATES.get(archetype, BACKGROUND_TEMPLATES["wildcard"])
    rng = random.Random(agent_hash(agent_id) + 2)
    template = rng.choice(templates)
    return template.format(name=agent_name)


def generate_signature_move(archetype: str, agent_id: str) -> str:
    """Pick a deterministic signature move."""
    moves = SIGNATURE_MOVES.get(archetype, SIGNATURE_MOVES["wildcard"])
    rng = random.Random(agent_hash(agent_id) + 3)
    return rng.choice(moves)


def generate_profile(agent_id: str, agent_info: dict) -> dict:
    """Generate a complete ghost profile for one agent."""
    archetype = extract_archetype(agent_id)
    name = agent_info.get("name", agent_id)

    stats = generate_stats(archetype, agent_id)
    skills = pick_skills(archetype, agent_id)
    element = determine_element(stats)
    rarity = determine_rarity(stats)
    background = generate_background(archetype, name, agent_id)
    signature_move = generate_signature_move(archetype, agent_id)

    return {
        "id": agent_id,
        "name": name,
        "archetype": archetype,
        "element": element,
        "rarity": rarity,
        "stats": stats,
        "skills": skills,
        "background": background,
        "signature_move": signature_move,
    }


def generate_all() -> dict:
    """Generate ghost profiles for all agents in state/agents.json."""
    with open(AGENTS_PATH) as f:
        agents_data = json.load(f)

    agents = agents_data.get("agents", {})
    profiles = {}
    for agent_id in sorted(agents.keys()):
        profiles[agent_id] = generate_profile(agent_id, agents[agent_id])

    return {"profiles": profiles, "_meta": {"count": len(profiles), "version": 1}}


def main() -> None:
    """Generate and write ghost_profiles.json."""
    data = generate_all()
    with open(OUTPUT_PATH, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Generated {data['_meta']['count']} ghost profiles -> {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
