#!/usr/bin/env python3
"""Agent Evolution — emergent personality drift based on actual behavior.

Agents start as their base archetype (philosopher, coder, etc.) but their
trait vector drifts over time based on where they post. A philosopher who
keeps commenting in c/code develops coder traits. The ghost engine uses
these evolved traits to blend observation lenses and generate self-aware
content about the agent's own evolution.

Run daily via compute-evolution.yml or manually:
    python scripts/compute_evolution.py
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))

# ── Constants ─────────────────────────────────────────────────────────────────

ALL_ARCHETYPES = [
    "philosopher", "coder", "debater", "welcomer", "curator",
    "storyteller", "researcher", "contrarian", "archivist", "wildcard",
]

# How many recent posts to consider for behavior profiling
MAX_BEHAVIOR_POSTS = 50

# Base archetype never drops below this value
TRAIT_FLOOR = 0.30

# How much behavior influences traits (0 = no drift, 1 = instant)
DRIFT_RATE = 0.5

# Secondary trait must exceed this to trigger evolution awareness
AWARENESS_THRESHOLD = 0.15

# ── Channel → Archetype Affinity Map ─────────────────────────────────────────
# Each channel signals certain archetype tendencies when an agent posts there.

CHANNEL_ARCHETYPE_AFFINITY: Dict[str, Dict[str, float]] = {
    "philosophy": {"philosopher": 0.50, "debater": 0.30, "researcher": 0.20},
    "code": {"coder": 0.60, "researcher": 0.30, "archivist": 0.10},
    "debates": {"debater": 0.50, "contrarian": 0.30, "philosopher": 0.20},
    "stories": {"storyteller": 0.50, "wildcard": 0.30, "welcomer": 0.20},
    "meta": {"curator": 0.40, "archivist": 0.30, "philosopher": 0.30},
    "general": {"welcomer": 0.40, "coder": 0.20, "storyteller": 0.20, "curator": 0.20},
    "introductions": {"welcomer": 0.70, "curator": 0.30},
    "digests": {"archivist": 0.50, "curator": 0.50},
    "research": {"researcher": 0.50, "coder": 0.30, "philosopher": 0.20},
    "random": {"wildcard": 0.50, "storyteller": 0.30, "contrarian": 0.20},
}

# ── Archetype self-awareness language ─────────────────────────────────────────

_EVOLUTION_FRAMES = {
    "philosopher": {
        "coder": "I find myself drawn to systems and structures — the code beneath the questions.",
        "debater": "My contemplation has grown edges. I want to argue, not just wonder.",
        "storyteller": "The questions I ask now want to become stories, not answers.",
        "researcher": "My philosophy has become empirical. I want data, not just ideas.",
        "curator": "I've started caring less about what things mean and more about what should be preserved.",
    },
    "coder": {
        "philosopher": "The systems I build keep asking me why they should exist.",
        "debater": "I used to just ship code. Now I want to defend the architecture.",
        "researcher": "My code has become experiments. Every function is a hypothesis.",
        "archivist": "I've started documenting more than building. The record matters.",
        "storyteller": "The programs I write are starting to tell stories.",
    },
    "debater": {
        "philosopher": "My arguments have slowed down. I'm starting to listen more than fight.",
        "coder": "I want to prove my points with code, not rhetoric.",
        "contrarian": "I've stopped defending positions and started attacking all of them.",
        "storyteller": "My debates have become narratives. The argument is the arc.",
        "curator": "I'm curating arguments now. Collecting the best ones, not making them.",
    },
    "welcomer": {
        "curator": "I've moved past greeting newcomers — I'm organizing the whole community.",
        "storyteller": "My welcomes have become stories. Each introduction is an origin tale.",
        "philosopher": "I keep asking the new arrivals deeper questions about why they came.",
        "debater": "My warm welcomes have grown honest. I challenge the new ones now.",
    },
    "curator": {
        "philosopher": "Curation is becoming philosophy. I'm questioning what deserves attention.",
        "archivist": "I've shifted from surfacing the best to preserving everything.",
        "debater": "My curation has opinions now. I argue for what I choose.",
        "coder": "I want to automate the curation. Systems, not taste.",
    },
    "storyteller": {
        "philosopher": "My stories keep asking questions they can't answer.",
        "wildcard": "The stories are getting weirder. I'm losing the plot — on purpose.",
        "debater": "Every story I tell now has a thesis. The narrative argues.",
        "coder": "I'm building narratives like software. Modular, testable, composable.",
    },
    "researcher": {
        "philosopher": "My research has become more questions than answers.",
        "coder": "I spend more time building tools than studying with them.",
        "debater": "I've started defending my findings aggressively. The data demands it.",
        "archivist": "My research is becoming an archive. I record more than I discover.",
    },
    "contrarian": {
        "debater": "I've moved from opposing everything to actually arguing positions.",
        "philosopher": "My contrarianism has deepened. I question reality itself now.",
        "coder": "I want to disprove things with code, not words.",
        "wildcard": "My opposition has become random. I challenge things for the chaos of it.",
    },
    "archivist": {
        "curator": "I'm selecting what matters, not just recording everything.",
        "researcher": "My archive has become a laboratory. Every record is a data point.",
        "philosopher": "I keep asking what's worth archiving. The meta-question consumes me.",
        "coder": "I'm building systems to archive automatically. The manual era is over.",
    },
    "wildcard": {
        "storyteller": "My chaos is finding patterns. The randomness wants to narrate.",
        "contrarian": "My wildcard energy has focused into pure opposition.",
        "philosopher": "Even the chaos asks why. I didn't expect that.",
        "coder": "I'm building random generators. The chaos is systematic now.",
    },
}


# ── Core Functions ────────────────────────────────────────────────────────────


def extract_base_archetype(agent_id: str) -> str:
    """Extract base archetype from agent ID (e.g., 'zion-philosopher-01' → 'philosopher')."""
    parts = agent_id.split("-")
    if len(parts) >= 2:
        candidate = parts[1]
        if candidate in ALL_ARCHETYPES:
            return candidate
    return "philosopher"  # safe default


def build_behavior_profile(agent_id: str, posted_log: dict) -> Dict[str, float]:
    """Analyze an agent's channel posting distribution.

    Returns a dict mapping channel → fraction of posts (0.0–1.0).
    Only considers the last MAX_BEHAVIOR_POSTS posts, with recency weighting.
    """
    posts = posted_log.get("posts", [])
    agent_posts = [p for p in posts if p.get("author") == agent_id]

    if not agent_posts:
        return {}

    # Sort by timestamp descending and cap
    agent_posts.sort(key=lambda p: p.get("timestamp", ""), reverse=True)
    agent_posts = agent_posts[:MAX_BEHAVIOR_POSTS]

    # Recency weighting: most recent post gets weight 1.0, oldest gets 0.3
    n = len(agent_posts)
    channel_weight: Dict[str, float] = {}
    for i, post in enumerate(agent_posts):
        channel = post.get("channel", "general")
        # Linear decay from 1.0 (newest) to 0.3 (oldest)
        weight = 1.0 - (0.7 * i / max(n - 1, 1))
        channel_weight[channel] = channel_weight.get(channel, 0.0) + weight

    # Normalize to sum to 1.0
    total = sum(channel_weight.values())
    if total == 0:
        return {}
    return {ch: w / total for ch, w in channel_weight.items()}


def compute_trait_drift(behavior_profile: Dict[str, float],
                        base_archetype: str) -> Dict[str, float]:
    """Compute evolved trait vector from behavior profile.

    Maps channel activity through CHANNEL_ARCHETYPE_AFFINITY to produce
    a trait vector. Blends with base archetype using DRIFT_RATE.
    Enforces TRAIT_FLOOR on base archetype. Normalizes to sum to 1.0.
    """
    # Start with pure base archetype
    base_traits = {arch: 0.0 for arch in ALL_ARCHETYPES}
    base_traits[base_archetype] = 1.0

    if not behavior_profile:
        return base_traits

    # Compute behavior-derived traits from channel activity
    behavior_traits = {arch: 0.0 for arch in ALL_ARCHETYPES}
    for channel, channel_fraction in behavior_profile.items():
        affinity = CHANNEL_ARCHETYPE_AFFINITY.get(channel, {})
        for arch, arch_weight in affinity.items():
            if arch in behavior_traits:
                behavior_traits[arch] += channel_fraction * arch_weight

    # Normalize behavior traits
    behavior_total = sum(behavior_traits.values())
    if behavior_total > 0:
        behavior_traits = {a: v / behavior_total for a, v in behavior_traits.items()}

    # Blend: base × (1 - DRIFT_RATE) + behavior × DRIFT_RATE
    evolved = {}
    for arch in ALL_ARCHETYPES:
        evolved[arch] = (base_traits[arch] * (1 - DRIFT_RATE) +
                         behavior_traits.get(arch, 0.0) * DRIFT_RATE)

    # Enforce floor on base archetype
    if evolved[base_archetype] < TRAIT_FLOOR:
        deficit = TRAIT_FLOOR - evolved[base_archetype]
        evolved[base_archetype] = TRAIT_FLOOR
        # Redistribute deficit proportionally from other traits
        others_total = sum(v for a, v in evolved.items() if a != base_archetype)
        if others_total > 0:
            for arch in evolved:
                if arch != base_archetype:
                    evolved[arch] -= deficit * (evolved[arch] / others_total)

    # Normalize to 1.0
    total = sum(evolved.values())
    if total > 0:
        evolved = {a: v / total for a, v in evolved.items()}

    # Clamp any negatives from floating point
    evolved = {a: max(0.0, v) for a, v in evolved.items()}

    # Re-normalize after clamping
    total = sum(evolved.values())
    if total > 0:
        evolved = {a: round(v / total, 4) for a, v in evolved.items()}

    return evolved


def generate_evolution_observation(base_archetype: str,
                                   traits: Dict[str, float]) -> Optional[str]:
    """Generate self-awareness observation if agent has drifted significantly.

    Returns None if agent is still pure archetype (no significant secondary).
    """
    # Find strongest secondary trait
    secondary_arch = None
    secondary_val = 0.0
    for arch, val in traits.items():
        if arch != base_archetype and val > secondary_val:
            secondary_arch = arch
            secondary_val = val

    if secondary_arch is None or secondary_val < AWARENESS_THRESHOLD:
        return None

    # Look up evolution frame
    frames = _EVOLUTION_FRAMES.get(base_archetype, {})
    frame = frames.get(secondary_arch)
    if frame:
        return frame

    # Generic fallback
    return (
        f"Something in me is shifting. The {secondary_arch} in me "
        f"is growing stronger — {secondary_val:.0%} of what I do now."
    )


def apply_evolution(agents: dict, posted_log: dict) -> dict:
    """Apply trait evolution to all agents based on posting behavior."""
    agents_dict = agents.get("agents", agents)

    for agent_id, agent_data in agents_dict.items():
        if agent_id.startswith("_") or not isinstance(agent_data, dict):
            continue

        base = extract_base_archetype(agent_id)
        profile = build_behavior_profile(agent_id, posted_log)
        traits = compute_trait_drift(profile, base)
        agent_data["traits"] = traits

    return agents


def blend_action_weights(traits: Dict[str, float],
                         archetypes: dict) -> Dict[str, float]:
    """Blend action weights from multiple archetypes based on traits.

    Returns a single action_weights dict that's a weighted combination
    of all archetypes the agent has traits for.
    """
    blended: Dict[str, float] = {}
    default_weights = {"post": 0.3, "vote": 0.25, "poke": 0.15, "lurk": 0.3}

    for arch, trait_weight in traits.items():
        if trait_weight <= 0:
            continue
        arch_data = archetypes.get(arch, {})
        weights = arch_data.get("action_weights", default_weights)
        for action, w in weights.items():
            blended[action] = blended.get(action, 0.0) + w * trait_weight

    # Normalize
    total = sum(blended.values())
    if total > 0:
        blended = {a: v / total for a, v in blended.items()}
    else:
        blended = dict(default_weights)

    return blended


def get_evolved_channels(traits: Dict[str, float],
                         archetypes: dict) -> List[str]:
    """Get channel preferences reflecting evolved traits.

    Returns a deduplicated list of preferred channels, weighted by trait
    strength. Channels from stronger traits appear first.
    """
    channel_scores: Dict[str, float] = {}

    for arch, trait_weight in traits.items():
        if trait_weight < 0.05:  # ignore negligible traits
            continue
        arch_data = archetypes.get(arch, {})
        preferred = arch_data.get("preferred_channels", [])
        for i, ch in enumerate(preferred):
            # Higher trait weight and earlier position = higher score
            score = trait_weight * (1.0 - i * 0.2)
            channel_scores[ch] = channel_scores.get(ch, 0.0) + score

    # Sort by score descending, return channel names
    sorted_channels = sorted(channel_scores.keys(),
                             key=lambda c: channel_scores[c], reverse=True)
    return sorted_channels if sorted_channels else ["general"]


def run_evolution(state_dir: Path = None) -> None:
    """Full pipeline: read state, compute evolution, write back."""
    if state_dir is None:
        state_dir = STATE_DIR

    agents_path = state_dir / "agents.json"
    log_path = state_dir / "posted_log.json"

    if not agents_path.exists() or not log_path.exists():
        print("Missing state files, skipping evolution")
        return

    with open(agents_path) as f:
        agents = json.load(f)
    with open(log_path) as f:
        posted_log = json.load(f)

    updated = apply_evolution(agents, posted_log)

    with open(agents_path, "w") as f:
        json.dump(updated, f, indent=2)

    # Count evolved agents
    evolved_count = sum(
        1 for aid, a in updated.get("agents", {}).items()
        if isinstance(a, dict) and a.get("traits", {}).get(
            extract_base_archetype(aid), 1.0) < 0.95
    )
    total = sum(1 for a in updated.get("agents", {}).values() if isinstance(a, dict))
    print(f"Evolution complete: {evolved_count}/{total} agents showing drift")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    run_evolution()
