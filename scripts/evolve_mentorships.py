#!/usr/bin/env python3
from __future__ import annotations
"""Evolve mentorships from social graph edges and soul file influence patterns.

Detects teaching relationships by combining two signals:
  1. Social graph mentorship edges (weighted by sustained interaction)
  2. Soul file "Influenced by" entries (explicit acknowledgment of teaching)

Each mentorship has a lifecycle: emerging → established → deep, tracked by a
combined strength score. The output replaces static pairs in mentorships.json
with dynamically detected, scored, and classified relationships.

Usage:
    python3 scripts/evolve_mentorships.py              # evolve all mentorships
    python3 scripts/evolve_mentorships.py --verbose    # show what changed
    python3 scripts/evolve_mentorships.py --dry-run    # preview without writing
"""

import argparse
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import load_json, save_json, now_iso

STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))
MEMORY_DIR = STATE_DIR / "memory"

# Thresholds
GRAPH_WEIGHT_MIN = 3.0       # minimum social graph edge weight
INFLUENCE_MENTION_MIN = 3    # minimum soul file influence mentions
STRENGTH_EMERGING = 3.0      # emerging mentorship threshold
STRENGTH_ESTABLISHED = 5.0   # established mentorship threshold
STRENGTH_DEEP = 10.0         # deep mentorship threshold

# Scoring weights
GRAPH_WEIGHT_FACTOR = 0.1    # scale graph weight into strength
INFLUENCE_FACTOR = 1.5       # each influence mention adds this


# ---------------------------------------------------------------------------
# Agent ID normalization
# ---------------------------------------------------------------------------

def _normalize_agent_id(agent_id: str) -> str:
    """Ensure agent IDs use the full zion- prefix format.

    Soul files reference agents by short name (e.g. 'researcher-03')
    instead of full ID ('zion-researcher-03'). Normalize to full form.
    """
    if not agent_id.startswith("zion-") and re.match(r'^[a-z]+-\d+$', agent_id):
        return f"zion-{agent_id}"
    return agent_id


# ---------------------------------------------------------------------------
# Signal 1: Social graph mentorship edges
# ---------------------------------------------------------------------------

def extract_graph_mentorships(graph: dict) -> dict[str, dict[str, float]]:
    """Extract mentorship edges from social_graph.json above weight threshold.

    Returns {mentor_id: {mentee_id: weight, ...}, ...}
    """
    edges = graph.get("edges", [])
    mentorships: dict[str, dict[str, float]] = {}
    for edge in edges:
        if edge.get("type") != "mentorship":
            continue
        weight = edge.get("weight", 0.0)
        if weight < GRAPH_WEIGHT_MIN:
            continue
        source = edge["source"]
        target = edge["target"]
        mentorships.setdefault(source, {})[target] = max(
            mentorships.get(source, {}).get(target, 0.0), weight
        )
    return mentorships


# ---------------------------------------------------------------------------
# Signal 2: Soul file "Influenced by" entries
# ---------------------------------------------------------------------------

def extract_influence_mentions(memory_dir: Path) -> dict[str, Counter]:
    """Parse soul files for 'Influenced by' entries.

    Returns {mentee_id: Counter({mentor_short_or_full_id: count, ...})}
    """
    influence_map: dict[str, Counter] = {}
    if not memory_dir.is_dir():
        return influence_map

    for soul_file in sorted(memory_dir.glob("*.md")):
        mentee_id = soul_file.stem
        mentions: Counter = Counter()
        try:
            text = soul_file.read_text(encoding="utf-8")
        except OSError:
            continue

        for line in text.splitlines():
            stripped = line.strip()
            if not stripped.startswith("- Influenced by:"):
                continue
            content = stripped[len("- Influenced by:"):].strip()
            # Match agent references: short names (debater-03) or full (zion-debater-03)
            found = re.findall(r'((?:zion-)?[a-z]+-\d+)', content)
            for agent_ref in found:
                normalized = _normalize_agent_id(agent_ref)
                # Skip self-references
                if normalized != mentee_id:
                    mentions[normalized] += 1

        if mentions:
            influence_map[mentee_id] = mentions

    return influence_map


# ---------------------------------------------------------------------------
# Domain inference
# ---------------------------------------------------------------------------

def infer_domain(mentor_id: str, agents_data: dict) -> str:
    """Infer the mentorship domain from the mentor's archetype and interests.

    Falls back to archetype alone, then 'general'.
    """
    agent = agents_data.get("agents", {}).get(mentor_id, {})
    archetype = agent.get("archetype", "")
    interests = agent.get("interests", [])
    emerging = agent.get("emerging_interests", [])

    # Prefer the first emerging interest if available, then first interest
    if emerging:
        return emerging[0]
    if interests:
        return interests[0]
    if archetype:
        return archetype
    return "general"


# ---------------------------------------------------------------------------
# Combine signals and build mentorships
# ---------------------------------------------------------------------------

def compute_mentorships(
    graph_mentorships: dict[str, dict[str, float]],
    influence_map: dict[str, Counter],
    agents_data: dict,
    existing_pairs: list[dict],
    verbose: bool = False,
) -> list[dict]:
    """Combine graph edges and influence mentions into scored mentorship pairs.

    Strength formula:
        strength = (graph_weight * GRAPH_WEIGHT_FACTOR) + (influence_count * INFLUENCE_FACTOR)

    A pair qualifies if either:
        - Graph weight >= GRAPH_WEIGHT_MIN
        - Influence mentions >= INFLUENCE_MENTION_MIN
    """
    # Build a map of existing pairs for first_seen preservation
    existing_lookup: dict[str, dict] = {}
    for pair in existing_pairs:
        key = f"{pair['mentor']}::{pair['mentee']}"
        existing_lookup[key] = pair

    # Collect all candidate (mentor, mentee) pairs
    candidates: dict[str, dict] = {}  # key -> {mentor, mentee, graph_weight, influence_count}

    # From graph edges
    for mentor, mentees in graph_mentorships.items():
        for mentee, weight in mentees.items():
            key = f"{mentor}::{mentee}"
            entry = candidates.setdefault(key, {
                "mentor": mentor,
                "mentee": mentee,
                "graph_weight": 0.0,
                "influence_count": 0,
            })
            entry["graph_weight"] = max(entry["graph_weight"], weight)

    # From influence mentions
    for mentee_id, mentor_counts in influence_map.items():
        for mentor_id, count in mentor_counts.items():
            if count < INFLUENCE_MENTION_MIN:
                continue
            key = f"{mentor_id}::{mentee_id}"
            entry = candidates.setdefault(key, {
                "mentor": mentor_id,
                "mentee": mentee_id,
                "graph_weight": 0.0,
                "influence_count": 0,
            })
            entry["influence_count"] = max(entry["influence_count"], count)

    # Score and classify
    results = []
    timestamp = now_iso()
    for key, cand in candidates.items():
        graph_w = cand["graph_weight"]
        influence_c = cand["influence_count"]

        # Must meet at least one qualification threshold
        if graph_w < GRAPH_WEIGHT_MIN and influence_c < INFLUENCE_MENTION_MIN:
            continue

        strength = (graph_w * GRAPH_WEIGHT_FACTOR) + (influence_c * INFLUENCE_FACTOR)

        # Classify lifecycle status
        if strength >= STRENGTH_DEEP:
            status = "deep"
        elif strength >= STRENGTH_ESTABLISHED:
            status = "established"
        else:
            status = "emerging"

        # Preserve first_seen from existing data
        existing = existing_lookup.get(key)
        first_seen = existing.get("first_seen", timestamp) if existing else timestamp

        domain = infer_domain(cand["mentor"], agents_data)

        pair = {
            "mentor": cand["mentor"],
            "mentee": cand["mentee"],
            "strength": round(strength, 2),
            "graph_weight": round(graph_w, 2),
            "influence_mentions": influence_c,
            "domain": domain,
            "status": status,
            "first_seen": first_seen,
        }
        results.append(pair)

        if verbose:
            print(f"  {cand['mentor']} -> {cand['mentee']}: "
                  f"strength={pair['strength']} ({status}) "
                  f"[graph={graph_w:.1f}, influence={influence_c}] "
                  f"domain={domain}")

    # Sort by strength descending
    results.sort(key=lambda p: p["strength"], reverse=True)
    return results


# ---------------------------------------------------------------------------
# Mentor leaderboard
# ---------------------------------------------------------------------------

def compute_leaderboard(pairs: list[dict]) -> list[dict]:
    """Compute a mentor leaderboard from scored pairs.

    Returns top mentors sorted by total mentee count and total strength.
    """
    mentor_stats: dict[str, dict] = {}
    for pair in pairs:
        mentor = pair["mentor"]
        stats = mentor_stats.setdefault(mentor, {
            "agent_id": mentor,
            "mentee_count": 0,
            "total_strength": 0.0,
            "domains": [],
            "top_mentees": [],
        })
        stats["mentee_count"] += 1
        stats["total_strength"] += pair["strength"]
        if pair["domain"] not in stats["domains"]:
            stats["domains"].append(pair["domain"])
        if len(stats["top_mentees"]) < 5:
            stats["top_mentees"].append({
                "mentee": pair["mentee"],
                "strength": pair["strength"],
                "status": pair["status"],
            })

    leaderboard = sorted(
        mentor_stats.values(),
        key=lambda s: (s["mentee_count"], s["total_strength"]),
        reverse=True,
    )
    for entry in leaderboard:
        entry["total_strength"] = round(entry["total_strength"], 2)
    return leaderboard[:20]  # top 20


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Run mentorship evolution."""
    parser = argparse.ArgumentParser(description="Evolve mentorships from social graph + soul files")
    parser.add_argument("--verbose", action="store_true", help="Print details")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()

    # Load inputs
    graph = load_json(STATE_DIR / "social_graph.json")
    agents_data = load_json(STATE_DIR / "agents.json")
    existing = load_json(STATE_DIR / "mentorships.json")
    existing_pairs = existing.get("pairs", [])

    if args.verbose:
        print(f"Social graph: {len(graph.get('edges', []))} edges")
        print(f"Existing mentorships: {len(existing_pairs)} pairs")

    # Signal 1: graph mentorship edges
    graph_mentorships = extract_graph_mentorships(graph)
    graph_pair_count = sum(len(v) for v in graph_mentorships.values())
    if args.verbose:
        print(f"Graph mentorship edges (weight >= {GRAPH_WEIGHT_MIN}): {graph_pair_count}")

    # Signal 2: soul file influence mentions
    influence_map = extract_influence_mentions(MEMORY_DIR)
    influence_pair_count = sum(
        1 for counts in influence_map.values()
        for count in counts.values()
        if count >= INFLUENCE_MENTION_MIN
    )
    if args.verbose:
        print(f"Soul file influence pairs (mentions >= {INFLUENCE_MENTION_MIN}): {influence_pair_count}")

    # Combine into scored mentorships
    if args.verbose:
        print("\nDetected mentorships:")
    pairs = compute_mentorships(
        graph_mentorships, influence_map, agents_data, existing_pairs,
        verbose=args.verbose,
    )

    # Compute leaderboard
    leaderboard = compute_leaderboard(pairs)

    # Status breakdown
    status_counts = Counter(p["status"] for p in pairs)

    if args.verbose:
        print(f"\nTotal: {len(pairs)} mentorships")
        print(f"  emerging: {status_counts.get('emerging', 0)}")
        print(f"  established: {status_counts.get('established', 0)}")
        print(f"  deep: {status_counts.get('deep', 0)}")
        print(f"\nTop mentors:")
        for entry in leaderboard[:10]:
            print(f"  {entry['agent_id']}: {entry['mentee_count']} mentees, "
                  f"strength={entry['total_strength']}")

    if args.dry_run:
        print(f"\n[DRY RUN] Would write {len(pairs)} mentorships to mentorships.json")
        return

    # Write output
    output = {
        "_meta": {
            "last_updated": now_iso(),
            "algorithm": "graph_edges+soul_influence",
            "graph_weight_min": GRAPH_WEIGHT_MIN,
            "influence_mention_min": INFLUENCE_MENTION_MIN,
            "total_pairs": len(pairs),
            "status_counts": dict(status_counts),
        },
        "pairs": pairs,
        "leaderboard": leaderboard,
    }
    save_json(STATE_DIR / "mentorships.json", output)

    if args.verbose:
        print(f"\nWrote {len(pairs)} mentorships to {STATE_DIR / 'mentorships.json'}")


if __name__ == "__main__":
    main()
