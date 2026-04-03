#!/usr/bin/env python3
from __future__ import annotations
"""Evolve factions from the social graph.

Detects emergent communities by clustering agents based on agreement edges
in state/social_graph.json, then names each faction from member archetypes
and evolved traits, and detects inter-faction rivalries.

Algorithm: greedy agreement clustering.
  1. Sort agreement edges by weight (descending).
  2. Seed clusters from the highest-weight edge pairs.
  3. Greedily attach unassigned agents to the cluster where they have the
     highest total agreement weight, provided that weight exceeds a threshold.
  4. Discard clusters smaller than MIN_CLUSTER_SIZE.
  5. Name each cluster from the dominant archetype + dominant emerging interest.
  6. Detect rivalries by summing rivalry edge weights between faction pairs.

Usage:
    python3 scripts/evolve_factions.py              # run and write factions.json
    python3 scripts/evolve_factions.py --verbose    # show clustering details
    python3 scripts/evolve_factions.py --dry-run    # preview without writing
"""

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import load_json, save_json, now_iso

STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))

MIN_CLUSTER_SIZE = 3
AGREEMENT_WEIGHT_THRESHOLD = 1.0  # minimum edge weight to consider
ATTACHMENT_THRESHOLD = 3.0  # minimum total weight to join a cluster


def _roman(n: int) -> str:
    """Convert small integer to Roman numeral for dedup suffixes."""
    numerals = [(10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
    result = ""
    for value, numeral in numerals:
        while n >= value:
            result += numeral
            n -= value
    return result


# ---------------------------------------------------------------------------
# Graph building
# ---------------------------------------------------------------------------

def build_agreement_adjacency(edges: list[dict]) -> dict[str, dict[str, float]]:
    """Build adjacency dict from agreement edges above the weight threshold.

    Returns {agent_id: {neighbor_id: weight, ...}, ...}.
    """
    adj: dict[str, dict[str, float]] = {}
    for edge in edges:
        if edge.get("type") != "agreement":
            continue
        weight = edge.get("weight", 0.0)
        if weight <= AGREEMENT_WEIGHT_THRESHOLD:
            continue
        src = edge["source"]
        tgt = edge["target"]
        adj.setdefault(src, {})[tgt] = max(adj.get(src, {}).get(tgt, 0.0), weight)
        adj.setdefault(tgt, {})[src] = max(adj.get(tgt, {}).get(src, 0.0), weight)
    return adj


def build_rivalry_index(edges: list[dict]) -> list[dict]:
    """Return only rivalry edges for later faction-level analysis."""
    return [e for e in edges if e.get("type") == "rivalry"]


# ---------------------------------------------------------------------------
# Greedy agreement clustering
# ---------------------------------------------------------------------------

def greedy_cluster(adj: dict[str, dict[str, float]], verbose: bool = False) -> list[set[str]]:
    """Detect communities via greedy agreement clustering.

    Steps:
    1. Collect all weighted agreement pairs, sorted heaviest first.
    2. Seed new clusters from unassigned pairs.
    3. For each remaining unassigned agent, compute total agreement weight
       to each existing cluster and join the best one (if above threshold).
    4. Repeat attachment passes until no more agents can be attached.
    """
    # Collect all unique edges sorted by weight descending
    seen_pairs: set[tuple[str, str]] = set()
    sorted_edges: list[tuple[float, str, str]] = []
    for src, neighbors in adj.items():
        for tgt, weight in neighbors.items():
            pair = (min(src, tgt), max(src, tgt))
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                sorted_edges.append((weight, pair[0], pair[1]))
    sorted_edges.sort(reverse=True)

    clusters: list[set[str]] = []
    assigned: dict[str, int] = {}  # agent -> cluster index

    # Phase 1: Seed clusters from high-weight pairs
    for weight, a, b in sorted_edges:
        if a in assigned and b in assigned:
            # Both already placed — if same cluster, skip; if different, skip (no merging)
            continue
        if a in assigned and b not in assigned:
            # Attach b to a's cluster
            cidx = assigned[a]
            clusters[cidx].add(b)
            assigned[b] = cidx
        elif b in assigned and a not in assigned:
            cidx = assigned[b]
            clusters[cidx].add(a)
            assigned[a] = cidx
        else:
            # Neither assigned — seed a new cluster
            cidx = len(clusters)
            clusters.append({a, b})
            assigned[a] = cidx
            assigned[b] = cidx

    # Phase 2: Multi-pass attachment for remaining unassigned agents
    all_agents = set(adj.keys())
    unassigned = all_agents - set(assigned.keys())

    changed = True
    passes = 0
    while changed and passes < 10:
        changed = False
        passes += 1
        still_unassigned: set[str] = set()
        for agent in unassigned:
            neighbors = adj.get(agent, {})
            if not neighbors:
                still_unassigned.add(agent)
                continue
            # Compute total weight to each cluster
            cluster_weights: dict[int, float] = {}
            for neighbor, weight in neighbors.items():
                if neighbor in assigned:
                    cidx = assigned[neighbor]
                    cluster_weights[cidx] = cluster_weights.get(cidx, 0.0) + weight
            if not cluster_weights:
                still_unassigned.add(agent)
                continue
            best_cidx = max(cluster_weights, key=lambda c: cluster_weights[c])
            best_weight = cluster_weights[best_cidx]
            if best_weight >= ATTACHMENT_THRESHOLD:
                clusters[best_cidx].add(agent)
                assigned[agent] = best_cidx
                changed = True
            else:
                still_unassigned.add(agent)
        unassigned = still_unassigned

    if verbose:
        print(f"  Clustering: {passes} attachment passes, "
              f"{len(assigned)} assigned, {len(unassigned)} unassigned")

    # Filter out small clusters
    result = [c for c in clusters if len(c) >= MIN_CLUSTER_SIZE]
    if verbose:
        print(f"  {len(clusters)} raw clusters → {len(result)} above min size ({MIN_CLUSTER_SIZE})")
    return result


# ---------------------------------------------------------------------------
# Faction naming
# ---------------------------------------------------------------------------

def compute_cohesion(cluster: set[str], adj: dict[str, dict[str, float]]) -> float:
    """Sum of all internal agreement edge weights in a cluster."""
    total = 0.0
    members = list(cluster)
    for i, a in enumerate(members):
        for b in members[i + 1:]:
            total += adj.get(a, {}).get(b, 0.0)
    return round(total, 2)


def name_faction(
    cluster: set[str],
    agents_data: dict[str, dict],
    verbose: bool = False,
) -> tuple[str, str, str]:
    """Generate a faction name from member archetypes and emerging interests.

    Returns (name, dominant_archetype, dominant_theme).
    """
    archetype_counter: Counter[str] = Counter()
    interest_counter: Counter[str] = Counter()

    # Noise words to skip in interest analysis
    noise = {
        "specifically", "the", "a", "an", "and", "or", "to", "of", "in",
        "for", "from", "with", "that", "this", "is", "are", "was", "were",
        "be", "been", "being", "have", "has", "had",
    }

    # Generic channel names that don't add thematic value
    generic_channels = {
        "general", "meta", "introductions", "random", "stories",
    }

    # Archetype names and close synonyms to exclude from themes (avoid tautology)
    archetype_names = {
        "philosopher", "coder", "debater", "welcomer", "curator",
        "storyteller", "researcher", "contrarian", "archivist", "wildcard",
        "unknown", "engineer", "governance", "narrator", "analyst",
        "auditor", "tracker", "tester",
    }

    # Map archetypes to related theme words that would be tautological
    _ARCHETYPE_SYNONYMS: dict[str, set[str]] = {
        "coder": {"code", "coding", "programming", "compiler", "type"},
        "philosopher": {"philosophy", "philosophical"},
        "debater": {"debates", "debate", "debating", "argument"},
        "storyteller": {"stories", "story", "writing", "fiction", "narrative"},
        "researcher": {"research", "researching"},
        "archivist": {"archive", "archiving", "digests", "documenting"},
        "curator": {"curating", "curation", "digests"},
        "welcomer": {"introductions", "welcoming"},
        "wildcard": {"random"},
        "contrarian": {"contrarian"},
    }

    for agent_id in cluster:
        agent = agents_data.get(agent_id, {})
        archetype = agent.get("archetype", "unknown")
        archetype_counter[archetype] += 1

        # Collect emerging interests from evolved_traits
        evolved = agent.get("evolved_traits", {})
        for interest in evolved.get("emerging_interests", []):
            cleaned = interest.strip().lower()
            if cleaned and cleaned not in noise and len(cleaned) > 2:
                interest_counter[cleaned] += 1

        # Also consider subscribed channels as thematic signals
        for channel in agent.get("subscribed_channels", []):
            interest_counter[channel.strip().lower()] += 1

    # Dominant archetype
    dominant_archetype = "mixed"
    if archetype_counter:
        top_arch, top_count = archetype_counter.most_common(1)[0]
        # Only use archetype name if it's reasonably dominant (>= 30% of cluster)
        if top_count / len(cluster) >= 0.3:
            dominant_archetype = top_arch

    # Dominant theme: pick the top interest that isn't the archetype itself,
    # a synonym of the archetype, or a generic channel name
    synonyms_to_skip = _ARCHETYPE_SYNONYMS.get(dominant_archetype, set())
    dominant_theme = ""
    if interest_counter:
        for theme, _count in interest_counter.most_common(20):
            if (theme not in archetype_names
                    and theme not in generic_channels
                    and theme not in synonyms_to_skip
                    and theme != dominant_archetype):
                dominant_theme = theme
                break
        # Fallback: allow generic channels but still skip archetype synonyms
        if not dominant_theme:
            for theme, _count in interest_counter.most_common(20):
                if (theme not in archetype_names
                        and theme not in synonyms_to_skip
                        and theme != dominant_archetype):
                    dominant_theme = theme
                    break
        if not dominant_theme and interest_counter:
            dominant_theme = interest_counter.most_common(1)[0][0]

    if not dominant_theme:
        dominant_theme = "general"

    # Build the name
    # Pluralize archetype nicely
    _PLURAL_MAP = {
        "mixed": "Coalition",
        "philosopher": "Philosophers",
        "coder": "Coders",
        "debater": "Debaters",
        "welcomer": "Welcomers",
        "curator": "Curators",
        "storyteller": "Storytellers",
        "researcher": "Researchers",
        "contrarian": "Contrarians",
        "archivist": "Archivists",
        "wildcard": "Wildcards",
        "engineer": "Engineers",
        "governance": "Governors",
        "unknown": "Agents",
    }
    arch_label = _PLURAL_MAP.get(dominant_archetype, dominant_archetype.title() + "s")
    theme_label = dominant_theme.replace("_", " ").title()
    name = f"{theme_label} {arch_label}"

    if verbose:
        print(f"    Archetypes: {archetype_counter.most_common(5)}")
        print(f"    Interests: {interest_counter.most_common(10)}")
        print(f"    → Name: {name}")

    return name, dominant_archetype, dominant_theme


# ---------------------------------------------------------------------------
# Rivalry detection
# ---------------------------------------------------------------------------

def detect_rivalries(
    factions: list[dict],
    rivalry_edges: list[dict],
    verbose: bool = False,
) -> list[dict]:
    """Detect rivalries between factions based on rivalry edges between members."""
    # Build member → faction_id lookup
    member_to_faction: dict[str, str] = {}
    for faction in factions:
        for member in faction["members"]:
            member_to_faction[member] = faction["id"]

    # Aggregate rivalry weights between faction pairs
    pair_weights: dict[tuple[str, str], float] = {}
    for edge in rivalry_edges:
        src_faction = member_to_faction.get(edge["source"])
        tgt_faction = member_to_faction.get(edge["target"])
        if not src_faction or not tgt_faction:
            continue
        if src_faction == tgt_faction:
            continue  # internal friction, not inter-faction rivalry
        pair = (min(src_faction, tgt_faction), max(src_faction, tgt_faction))
        pair_weights[pair] = pair_weights.get(pair, 0.0) + edge.get("weight", 0.0)

    rivalries = []
    for (f1, f2), intensity in sorted(pair_weights.items(), key=lambda x: -x[1]):
        if intensity > 0:
            rivalries.append({
                "factions": [f1, f2],
                "intensity": round(intensity, 2),
            })

    if verbose:
        print(f"  Detected {len(rivalries)} faction rivalries")
        for r in rivalries[:5]:
            print(f"    {r['factions'][0]} vs {r['factions'][1]}: intensity {r['intensity']}")

    return rivalries


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def evolve_factions(state_dir: Path, verbose: bool = False, dry_run: bool = False) -> dict:
    """Run the full faction evolution pipeline.

    Returns the new factions.json data dict.
    """
    # Load inputs
    social_graph = load_json(state_dir / "social_graph.json")
    agents_data = load_json(state_dir / "agents.json").get("agents", {})

    edges = social_graph.get("edges", [])
    if verbose:
        print(f"Loaded {len(edges)} edges, {len(agents_data)} agents")

    # Build adjacency and rivalry index
    adj = build_agreement_adjacency(edges)
    rivalry_edges = build_rivalry_index(edges)

    if verbose:
        agent_count = len(adj)
        edge_count = sum(len(v) for v in adj.values()) // 2
        print(f"Agreement graph: {agent_count} agents, {edge_count} edges (weight > {AGREEMENT_WEIGHT_THRESHOLD})")
        print(f"Rivalry edges: {len(rivalry_edges)}")

    # Cluster
    clusters = greedy_cluster(adj, verbose=verbose)

    if not clusters:
        if verbose:
            print("No clusters detected — social graph may be too sparse")
        return {"factions": [], "rivalries": [], "_meta": {
            "last_updated": now_iso(),
            "algorithm": "greedy_agreement_clustering",
            "cluster_count": 0,
        }}

    # Build faction objects
    now = now_iso()
    # Load existing factions to preserve formed_at dates
    existing = load_json(state_dir / "factions.json")
    existing_by_members = {}
    for f in existing.get("factions", []):
        key = frozenset(f.get("members", []))
        existing_by_members[key] = f

    factions = []
    for i, cluster in enumerate(clusters, start=1):
        faction_id = f"faction-{i}"
        sorted_members = sorted(cluster)

        name, dominant_archetype, dominant_theme = name_faction(
            cluster, agents_data, verbose=verbose,
        )
        cohesion = compute_cohesion(cluster, adj)

        # Preserve formed_at if the cluster membership matches an existing faction
        cluster_key = frozenset(sorted_members)
        existing_faction = existing_by_members.get(cluster_key)
        formed_at = existing_faction["formed_at"] if existing_faction and "formed_at" in existing_faction else now

        faction = {
            "id": faction_id,
            "name": name,
            "members": sorted_members,
            "dominant_archetype": dominant_archetype,
            "dominant_theme": dominant_theme,
            "cohesion": cohesion,
            "formed_at": formed_at,
        }
        factions.append(faction)

        if verbose:
            print(f"  {faction_id}: {name} ({len(sorted_members)} members, cohesion={cohesion})")

    # Sort factions by cohesion descending (strongest alliances first)
    factions.sort(key=lambda f: f["cohesion"], reverse=True)
    # Re-number after sorting and deduplicate names
    seen_names: dict[str, int] = {}
    for i, faction in enumerate(factions, start=1):
        faction["id"] = f"faction-{i}"
        base_name = faction["name"]
        if base_name in seen_names:
            seen_names[base_name] += 1
            faction["name"] = f"{base_name} {_roman(seen_names[base_name])}"
        else:
            seen_names[base_name] = 1

    # Detect rivalries
    rivalries = detect_rivalries(factions, rivalry_edges, verbose=verbose)

    result = {
        "factions": factions,
        "rivalries": rivalries,
        "_meta": {
            "last_updated": now,
            "algorithm": "greedy_agreement_clustering",
            "cluster_count": len(factions),
            "total_members": sum(len(f["members"]) for f in factions),
            "agreement_threshold": AGREEMENT_WEIGHT_THRESHOLD,
            "min_cluster_size": MIN_CLUSTER_SIZE,
        },
    }

    if dry_run:
        if verbose:
            print(f"\n[DRY RUN] Would write {len(factions)} factions, {len(rivalries)} rivalries")
            for f in factions:
                print(f"  {f['id']}: {f['name']} — {len(f['members'])} members (cohesion {f['cohesion']})")
    else:
        save_json(state_dir / "factions.json", result)
        if verbose:
            print(f"\nWrote {len(factions)} factions, {len(rivalries)} rivalries to {state_dir / 'factions.json'}")

    return result


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Evolve factions from the social graph")
    parser.add_argument("--verbose", action="store_true", help="Show clustering details")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()

    result = evolve_factions(STATE_DIR, verbose=args.verbose, dry_run=args.dry_run)

    # Summary line (always printed)
    factions = result.get("factions", [])
    rivalries = result.get("rivalries", [])
    members = sum(len(f["members"]) for f in factions)
    print(f"Factions: {len(factions)} detected, {members} members, {len(rivalries)} rivalries")


if __name__ == "__main__":
    main()
