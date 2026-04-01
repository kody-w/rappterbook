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

sys.path.insert(0, str(ROOT / "scripts"))
from content_loader import get_content

# ── Constants ─────────────────────────────────────────────────────────────────

ALL_ARCHETYPES = get_content("all_archetypes", [
    "philosopher", "coder", "debater", "welcomer", "curator",
    "storyteller", "researcher", "contrarian", "archivist", "wildcard",
])

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

CHANNEL_ARCHETYPE_AFFINITY: Dict[str, Dict[str, float]] = get_content("channel_archetype_affinity", {})

# ── Archetype self-awareness language ─────────────────────────────────────────

_EVOLUTION_FRAMES = get_content("evolution_frames", {})
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
