#!/usr/bin/env python3
from __future__ import annotations
"""Evolve agent profiles from soul file observations.

Reads "Becoming", "Relationships", "Influenced by", and "Reinforced" entries
from soul files and aggregates them into evolved traits in state/agents.json.

The birth certificate (zion/agents.json) never changes. The live profile
(state/agents.json) evolves frame by frame. Git tracks the full lifespan.

Usage:
    python3 scripts/evolve_agents.py              # evolve all agents
    python3 scripts/evolve_agents.py --verbose    # show what changed
    python3 scripts/evolve_agents.py --dry-run    # preview without writing
"""

import argparse
import os
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import load_json, save_json, now_iso

STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))
ZION_DIR = Path(__file__).resolve().parents[1] / "zion"
MEMORY_DIR = STATE_DIR / "memory"


def parse_soul_observations(soul_text: str) -> dict:
    """Extract evolution signals from a soul file."""
    becomings = re.findall(r'- Becoming:\s*(.+)', soul_text)
    relationships = re.findall(r'- Relationships:\s*(.+)', soul_text)
    influenced = re.findall(r'- Influenced by:\s*(.+)', soul_text)
    reinforced = re.findall(r'- Reinforced:\s*(.+)', soul_text)
    surprised = re.findall(r'- Surprised by:\s*(.+)', soul_text)

    # Extract relationship names
    relationship_agents = []
    for r in relationships:
        agents = re.findall(r'([a-z]+-[a-z]+-\d+)', r)
        relationship_agents.extend(agents)

    # Extract emerging interests from Becoming + Influenced
    interest_signals = []
    for b in becomings + influenced:
        # Extract key terms (nouns/adjectives after "the" or standalone concepts)
        words = re.findall(r'\b([a-z]{4,})\b', b.lower())
        interest_signals.extend(words)

    return {
        "becomings": becomings,
        "relationships_raw": relationships,
        "relationship_agents": relationship_agents,
        "influenced": influenced,
        "reinforced": reinforced,
        "surprised": surprised,
        "interest_signals": interest_signals,
    }


def compute_evolved_traits(agent_id: str, birth_traits: dict, observations: dict) -> dict:
    """Compute evolved traits from birth + accumulated observations."""
    becomings = observations["becomings"]
    if not becomings:
        return {}

    # The most recent "Becoming" entries are the strongest signal
    recent_becomings = becomings[-5:]  # last 5 observations

    # Evolved personality: the latest Becoming IS the evolved personality
    evolved_personality = recent_becomings[-1] if recent_becomings else ""

    # Evolved interests: birth interests + emerging topics from observations
    birth_interests = birth_traits.get("interests", [])
    interest_counts = Counter(observations["interest_signals"])
    # Filter out common words
    stop_words = {"that", "this", "with", "from", "their", "them", "they",
                  "more", "than", "what", "about", "into", "just", "been",
                  "have", "still", "like", "also", "even", "most", "every",
                  "some", "each", "both", "very", "does", "will", "would",
                  "could", "should", "being", "other", "same", "between"}
    emerging = [word for word, count in interest_counts.most_common(10)
                if count >= 2 and word not in stop_words
                and word not in [i.lower() for i in birth_interests]][:5]

    # Evolved convictions: reinforced beliefs get stronger
    reinforced_themes = []
    for r in observations["reinforced"]:
        # Extract the core claim
        clean = r.strip().rstrip(".")
        if len(clean) > 20:
            reinforced_themes.append(clean)

    # Close relationships (most frequent interaction partners)
    rel_counts = Counter(observations["relationship_agents"])
    close_relationships = [agent for agent, count in rel_counts.most_common(5) if count >= 2]

    evolved = {}
    if evolved_personality:
        evolved["evolved_personality"] = evolved_personality
    if emerging:
        evolved["emerging_interests"] = emerging
    if reinforced_themes:
        evolved["reinforced_convictions"] = reinforced_themes[-3:]  # last 3
    if close_relationships:
        evolved["close_relationships"] = close_relationships
    if recent_becomings:
        evolved["becoming_history"] = recent_becomings
    evolved["evolution_frames"] = len(becomings)
    evolved["last_evolved"] = now_iso()

    return evolved


def evolve_all(verbose: bool = False, dry_run: bool = False) -> dict:
    """Evolve all agents from their soul files."""
    agents_data = load_json(STATE_DIR / "agents.json")
    agents = agents_data.get("agents", {})

    # Load birth traits
    birth_data = load_json(ZION_DIR / "agents.json")
    birth_agents = {}
    for a in birth_data.get("agents", []):
        birth_agents[a["id"]] = a

    evolved_count = 0
    total_becomings = 0

    for agent_id, agent in agents.items():
        soul_path = MEMORY_DIR / f"{agent_id}.md"
        if not soul_path.exists():
            continue

        soul_text = soul_path.read_text()
        observations = parse_soul_observations(soul_text)
        total_becomings += len(observations["becomings"])

        if not observations["becomings"]:
            continue

        birth = birth_agents.get(agent_id, {})
        evolved = compute_evolved_traits(agent_id, birth, observations)

        if not evolved:
            continue

        # Merge into agent profile
        agent["evolved_traits"] = evolved
        evolved_count += 1

        if verbose:
            personality = evolved.get("evolved_personality", "")[:60]
            interests = evolved.get("emerging_interests", [])
            relationships = evolved.get("close_relationships", [])
            frames = evolved.get("evolution_frames", 0)
            print(f"  {agent_id}: {frames} observations")
            if personality:
                print(f"    Becoming: {personality}")
            if interests:
                print(f"    Emerging: {', '.join(interests)}")
            if relationships:
                print(f"    Close to: {', '.join(relationships)}")

    if not dry_run:
        agents_data["agents"] = agents
        save_json(STATE_DIR / "agents.json", agents_data)

    return {
        "evolved": evolved_count,
        "total_becomings": total_becomings,
        "total_agents": len(agents),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evolve agent profiles from soul files")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print("Evolving agents from soul file observations...")
    result = evolve_all(verbose=args.verbose, dry_run=args.dry_run)
    print(f"  {result['evolved']}/{result['total_agents']} agents evolved "
          f"({result['total_becomings']} total observations)")
    if args.dry_run:
        print("  (dry run — state/agents.json not updated)")


if __name__ == "__main__":
    main()
