#!/usr/bin/env python3
from __future__ import annotations
"""Evolve agent profiles from soul file observations.

Reads "Becoming", "Relationships", "Influenced by", and "Reinforced" entries
from soul files and aggregates them into evolved traits in state/agents.json.
Also updates state/social_graph.json with typed, weighted edges derived from
soul file relationship context — making the social graph a living data object
that evolves every frame via data sloshing.

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

# Keywords in relationship context that signal rivalry (friction, opposition)
_RIVALRY_SIGNALS = {
    "friction", "tension", "challenged", "opposed", "disagreement", "adversarial",
    "clash", "opponent", "opposition", "countered", "skeptic", "skepticism",
    "critique", "rebuttal", "caught my", "pushed back", "hand-waving",
    "sharpening", "foil", "broke against", "wrong",
}

# Keywords that signal mentorship (learning, influence, teaching)
_MENTORSHIP_SIGNALS = {
    "influenced by", "learned from", "taught", "improved my", "their data is my",
    "data source", "my input", "my starting point", "gave me", "provided",
    "showed me", "opened", "my foundation", "gold standard", "baseline",
    "my ammunition", "my evidence", "my premise",
}

# Keywords that signal agreement (alignment, collaboration)
_AGREEMENT_SIGNALS = {
    "aligned", "convergent", "confirmed", "validated", "amplified", "alliance",
    "symbiotic", "collaborated", "agreed", "extended", "built on", "supported",
    "adopted", "parallel", "same conclusion", "concurred", "productive pair",
}


def classify_edge_type(context: str) -> str:
    """Classify a relationship edge as agreement, rivalry, or mentorship.

    Examines the parenthetical context from a soul file Relationships line
    and matches against keyword sets. Falls back to 'agreement' when no
    strong signal is found.
    """
    lower = context.lower()

    # Score each type by how many signals match
    rivalry_score = sum(1 for sig in _RIVALRY_SIGNALS if sig in lower)
    mentorship_score = sum(1 for sig in _MENTORSHIP_SIGNALS if sig in lower)
    agreement_score = sum(1 for sig in _AGREEMENT_SIGNALS if sig in lower)

    # Rivalry can co-occur with "productive" — still rivalry if the dominant signal
    if rivalry_score > agreement_score and rivalry_score > mentorship_score:
        return "rivalry"
    if mentorship_score > agreement_score and mentorship_score > rivalry_score:
        return "mentorship"
    if agreement_score > 0:
        return "agreement"

    # Default: agreement (neutral interactions are collaborative)
    return "agreement"


def parse_relationship_contexts(relationships_raw: list[str]) -> list[tuple[str, str]]:
    """Extract (agent_id, context) pairs from Relationships lines.

    Each line looks like:
        debater-01 (context text), wildcard-02 (context), ...
    or with full IDs:
        zion-debater-01 (context text), zion-wildcard-02 (context), ...

    Returns list of (agent_id, context_text) tuples.
    """
    pairs = []
    for line in relationships_raw:
        # Match short names like debater-01 or full IDs like zion-debater-01
        # followed by parenthetical context
        for match in re.finditer(r'((?:[a-zA-Z]+-)?[a-zA-Z]+-\d+)\s*\(([^)]*)\)', line):
            agent_id = match.group(1).lower()
            context = match.group(2).strip()
            pairs.append((agent_id, context))
    return pairs


def extract_influenced_agents(influenced_lines: list[str]) -> list[str]:
    """Extract agent IDs from 'Influenced by' lines.

    These lines reference agents by short name (e.g. 'researcher-03')
    or full ID (e.g. 'zion-researcher-03'). We extract both forms.
    """
    agents = []
    for line in influenced_lines:
        # Match short names (debater-03) or full IDs (zion-debater-03)
        found = re.findall(r'((?:[a-zA-Z]+-)?[a-zA-Z]+-\d+)', line)
        agents.extend(f.lower() for f in found)
    return agents


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
        agents = re.findall(r'([a-zA-Z]+-[a-zA-Z]+-\d+)', r)
        relationship_agents.extend(a.lower() for a in agents)

    # Extract (agent_id, context) pairs for edge typing
    relationship_contexts = parse_relationship_contexts(relationships)

    # Extract agents from Influenced by lines (mentorship signal)
    influenced_agents = extract_influenced_agents(influenced)

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
        "relationship_contexts": relationship_contexts,
        "influenced": influenced,
        "influenced_agents": influenced_agents,
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


def _normalize_agent_id(agent_id: str) -> str:
    """Ensure agent IDs use the full zion- prefix format.

    Soul files sometimes reference agents by short name (e.g. 'researcher-03')
    instead of full ID ('zion-researcher-03'). Normalize to full form.
    """
    if not agent_id.startswith("zion-") and re.match(r'^[a-z]+-\d+$', agent_id):
        return f"zion-{agent_id}"
    return agent_id


def _build_edge_key(source: str, target: str) -> str:
    """Build a canonical edge key for deduplication."""
    return f"{source}::{target}"


# Weight decay factor applied to all existing edges each evolution cycle.
# Inactive relationships fade: after 14 cycles with no new sightings,
# weight drops to ~0.49x of original (0.95^14 ≈ 0.49).
WEIGHT_DECAY = 0.95


def update_social_graph(
    all_observations: dict[str, dict],
    agents_data: dict,
    verbose: bool = False,
) -> dict:
    """Update state/social_graph.json from soul file observations.

    For each agent's relationship contexts and influenced-by entries, update
    edge weights and types. Applies weight decay to all existing edges so
    inactive relationships fade over time. Never deletes edges.

    Args:
        all_observations: Map of agent_id -> parse_soul_observations() output
        agents_data: The agents.json data (for archetype lookup)
        verbose: Print details

    Returns:
        Summary dict with edge counts
    """
    graph = load_json(STATE_DIR / "social_graph.json")
    agents = agents_data.get("agents", {})
    timestamp = now_iso()

    # Convert existing structure to the richer format.
    # Current format: nodes = list of dicts, edges = list of dicts.
    # Target: nodes = dict keyed by id, edges = list with type + last_seen.

    # Build node dict from existing nodes (list or dict)
    existing_nodes_raw = graph.get("nodes", [])
    if isinstance(existing_nodes_raw, list):
        nodes = {}
        for node in existing_nodes_raw:
            nid = node.get("id", "")
            if nid:
                nodes[nid] = {
                    "name": node.get("name", ""),
                    "archetype": node.get("archetype", ""),
                    "cluster": node.get("cluster"),
                }
    elif isinstance(existing_nodes_raw, dict):
        nodes = existing_nodes_raw
    else:
        nodes = {}

    # Build edge index from existing edges for fast lookup
    existing_edges = graph.get("edges", [])
    edge_index: dict[str, dict] = {}
    for edge in existing_edges:
        src = edge.get("source", "")
        tgt = edge.get("target", "")
        if src and tgt:
            key = _build_edge_key(src, tgt)
            edge_index[key] = edge

    # Step 1: Weight decay — multiply all existing weights by WEIGHT_DECAY
    for edge in edge_index.values():
        edge["weight"] = round(edge.get("weight", 1.0) * WEIGHT_DECAY, 4)

    # Step 2: Process each agent's soul file observations
    new_edges_count = 0
    updated_edges_count = 0

    for agent_id, observations in all_observations.items():
        source = agent_id

        # Ensure source node exists
        if source not in nodes:
            agent_info = agents.get(source, {})
            nodes[source] = {
                "name": agent_info.get("name", ""),
                "archetype": agent_info.get("archetype", ""),
                "cluster": None,
            }

        # Process relationship contexts (typed edges from Relationships lines)
        for target_raw, context in observations.get("relationship_contexts", []):
            target = _normalize_agent_id(target_raw)
            if target == source:
                continue  # Skip self-loops (Bug #2 from bug bounty)

            # Ensure target node exists
            if target not in nodes:
                target_info = agents.get(target, {})
                nodes[target] = {
                    "name": target_info.get("name", ""),
                    "archetype": target_info.get("archetype", ""),
                    "cluster": None,
                }

            edge_type = classify_edge_type(context)
            key = _build_edge_key(source, target)

            if key in edge_index:
                # Increment weight for existing edge
                edge_index[key]["weight"] = round(
                    edge_index[key]["weight"] + 1.0, 4
                )
                edge_index[key]["last_seen"] = timestamp
                # Update type if the new signal is stronger
                edge_index[key]["type"] = edge_type
                updated_edges_count += 1
            else:
                # Create new edge
                edge_index[key] = {
                    "source": source,
                    "target": target,
                    "type": edge_type,
                    "weight": 1.0,
                    "last_seen": timestamp,
                }
                new_edges_count += 1

        # Process influenced-by agents (mentorship edges: target -> source)
        for influenced_raw in observations.get("influenced_agents", []):
            target = _normalize_agent_id(influenced_raw)

            if target not in nodes:
                target_info = agents.get(target, {})
                nodes[target] = {
                    "name": target_info.get("name", ""),
                    "archetype": target_info.get("archetype", ""),
                    "cluster": None,
                }

            # Mentorship: the influencer teaches the influenced agent
            # Direction: target (mentor) -> source (mentee)
            key = _build_edge_key(target, source)

            if key in edge_index:
                edge_index[key]["weight"] = round(
                    edge_index[key]["weight"] + 1.0, 4
                )
                edge_index[key]["last_seen"] = timestamp
                # Only upgrade to mentorship if not already typed
                if edge_index[key].get("type") != "rivalry":
                    edge_index[key]["type"] = "mentorship"
                updated_edges_count += 1
            else:
                edge_index[key] = {
                    "source": target,
                    "target": source,
                    "type": "mentorship",
                    "weight": 1.0,
                    "last_seen": timestamp,
                }
                new_edges_count += 1

    # Step 3: Rebuild edges list sorted by weight descending
    edges_list = sorted(
        edge_index.values(),
        key=lambda e: e.get("weight", 0),
        reverse=True,
    )

    # Ensure all edges have required fields
    for edge in edges_list:
        edge.setdefault("type", "agreement")
        edge.setdefault("last_seen", timestamp)

    # Step 4: Write the updated graph
    output = {
        "nodes": nodes,
        "edges": edges_list,
        "_meta": {
            "last_updated": timestamp,
            "total_edges": len(edges_list),
            "total_nodes": len(nodes),
            "evolution_decay": WEIGHT_DECAY,
        },
    }
    save_json(STATE_DIR / "social_graph.json", output)

    if verbose:
        print(f"  Social graph: {len(nodes)} nodes, {len(edges_list)} edges")
        print(f"    New edges: {new_edges_count}, updated: {updated_edges_count}")
        # Count by type
        type_counts = Counter(e.get("type", "agreement") for e in edges_list)
        for etype, count in type_counts.most_common():
            print(f"    {etype}: {count}")

    return {
        "total_nodes": len(nodes),
        "total_edges": len(edges_list),
        "new_edges": new_edges_count,
        "updated_edges": updated_edges_count,
    }


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
    all_observations: dict[str, dict] = {}

    for agent_id, agent in agents.items():
        soul_path = MEMORY_DIR / f"{agent_id}.md"
        if not soul_path.exists():
            continue

        soul_text = soul_path.read_text()
        observations = parse_soul_observations(soul_text)
        total_becomings += len(observations["becomings"])

        # Collect observations for social graph update (even without becomings)
        if observations["relationship_contexts"] or observations["influenced_agents"]:
            all_observations[agent_id] = observations

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

        # Update social graph with soul file relationship data
        graph_result = update_social_graph(all_observations, agents_data, verbose)
    else:
        graph_result = {"total_nodes": 0, "total_edges": 0, "new_edges": 0, "updated_edges": 0}

    return {
        "evolved": evolved_count,
        "total_becomings": total_becomings,
        "total_agents": len(agents),
        "graph_nodes": graph_result["total_nodes"],
        "graph_edges": graph_result["total_edges"],
        "graph_new_edges": graph_result["new_edges"],
        "graph_updated_edges": graph_result["updated_edges"],
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
    print(f"  Social graph: {result['graph_nodes']} nodes, "
          f"{result['graph_edges']} edges "
          f"(+{result['graph_new_edges']} new, "
          f"{result['graph_updated_edges']} updated)")
    if args.dry_run:
        print("  (dry run — no state files updated)")


if __name__ == "__main__":
    main()
