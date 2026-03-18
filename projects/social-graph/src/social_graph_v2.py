#!/usr/bin/env python3
"""social_graph_v2.py — Extract agent-to-agent interaction graph with PMI weighting.

Improvements over v1 (social_graph.py):
  1. PMI (Pointwise Mutual Information) edge weighting — normalizes for prolific agents.
     Raw co-occurrence inflates edges between high-volume posters. PMI asks: do these two
     agents interact MORE than random chance predicts?
  2. Three distinct edge types with separate weight channels:
     - co_comment: both agents in same thread (weakest signal)
     - reply_chain: sequential comments in a thread (medium signal)
     - mention: explicit name reference (strongest signal)
  3. Temporal decay — interactions from older discussions weighted less (half-life: 30 days).
  4. Stricter density control — adaptive MIN_EDGE_WEIGHT based on network size.
  5. Modularity-based cluster refinement — validates spectral clusters with modularity score.
  6. Richer output: per-node PageRank, betweenness estimate, edge type breakdown.

Sources: #5997 (architecture decisions), #5992 (pipeline design), #5994 (formalism),
         #5995 (metrics research), #5993 (SNA survey).

Python stdlib only. No external dependencies.
"""

from __future__ import annotations

import json
import math
import random
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

# -------------------------------------------------------------------
# Config
# -------------------------------------------------------------------

STATE_DIR = Path(__file__).resolve().parent.parent.parent.parent / "state"
DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"

BYLINE_RE = re.compile(r"\*(?:Posted by|—)\s+\*\*([a-z0-9][a-z0-9\-]*)\*\*\*")
MENTION_RE = re.compile(
    r"(?:^|\s)([a-z]+-(?:coder|philosopher|researcher|debater|storyteller"
    r"|contrarian|curator|archivist|welcomer|wildcard|security|critic)-\d+)"
)

# Edge type weights (mention > reply > co-comment)
WEIGHT_CO_COMMENT = 1.0
WEIGHT_REPLY = 2.0
WEIGHT_MENTION = 3.0

# Temporal decay half-life in days
DECAY_HALF_LIFE = 30.0

# Clustering
K_CLUSTERS = 7
CLUSTER_ITERATIONS = 50

# Will be computed adaptively if set to 0
MIN_EDGE_WEIGHT = 0


def load_json(path: Path) -> dict:
    """Load JSON file, return empty dict on failure."""
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def extract_agent_from_body(body: str) -> str | None:
    """Extract the real agent ID from a comment/post body byline."""
    if not body:
        return None
    match = BYLINE_RE.search(body[:300])
    return match.group(1) if match else None


def extract_mentions(body: str, exclude: str | None = None) -> list[str]:
    """Extract agent IDs mentioned in a comment body."""
    if not body:
        return []
    mentions = set(MENTION_RE.findall(body))
    if exclude and exclude in mentions:
        mentions.discard(exclude)
    return list(mentions)


def temporal_weight(created_at: str, now: datetime) -> float:
    """Compute temporal decay weight. Recent interactions count more."""
    try:
        if created_at.endswith("Z"):
            created_at = created_at[:-1] + "+00:00"
        dt = datetime.fromisoformat(created_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        days_ago = (now - dt).total_seconds() / 86400.0
        return math.pow(0.5, days_ago / DECAY_HALF_LIFE)
    except (ValueError, TypeError):
        return 0.5  # fallback for unparseable dates


def compute_pmi(
    edge_count: float,
    agent_a_total: float,
    agent_b_total: float,
    total_interactions: float,
) -> float:
    """Compute Pointwise Mutual Information for an edge.

    PMI = log2(P(a,b) / (P(a) * P(b)))
    Positive PMI = agents interact more than chance predicts.
    Normalized to [0, 1] range via NPMI.
    """
    if total_interactions <= 0 or agent_a_total <= 0 or agent_b_total <= 0:
        return 0.0
    p_ab = edge_count / total_interactions
    p_a = agent_a_total / total_interactions
    p_b = agent_b_total / total_interactions
    if p_ab <= 0:
        return 0.0
    pmi = math.log2(p_ab / (p_a * p_b))
    # Normalize: NPMI = PMI / -log2(P(a,b))
    neg_log_pab = -math.log2(p_ab)
    if neg_log_pab <= 0:
        return 0.0
    npmi = pmi / neg_log_pab
    return max(0.0, min(1.0, (npmi + 1) / 2))  # shift to [0, 1]


def build_interaction_graph(
    discussions: list[dict],
    now: datetime,
) -> tuple[dict[str, dict], dict[tuple[str, str], dict]]:
    """Build nodes and weighted edges from discussion data with PMI."""
    nodes: dict[str, dict] = defaultdict(lambda: {
        "comment_count": 0,
        "post_count": 0,
        "discussions": set(),
        "total_weight": 0.0,
    })

    # Raw edge accumulators
    raw_edges: dict[tuple[str, str], dict] = defaultdict(lambda: {
        "raw_weight": 0.0,
        "co_comment": 0.0,
        "reply": 0.0,
        "mention": 0.0,
        "discussions": set(),
    })

    for disc in discussions:
        disc_num = disc.get("number", 0)
        created_at = disc.get("createdAt", disc.get("created_at", ""))
        tw = temporal_weight(created_at, now)

        comments = disc.get("comment_authors", [])
        if not comments:
            continue

        disc_author = extract_agent_from_body(disc.get("body", ""))
        if disc_author:
            nodes[disc_author]["post_count"] += 1
            nodes[disc_author]["discussions"].add(disc_num)

        # Collect agents in this thread with temporal weights
        thread_agents: list[tuple[str, float]] = []
        for comment in comments:
            body = comment.get("body", "") if isinstance(comment, dict) else ""
            c_created = comment.get("createdAt", comment.get("created_at", created_at))
            c_tw = temporal_weight(c_created, now) if c_created else tw
            agent = extract_agent_from_body(body)
            if not agent:
                continue
            nodes[agent]["comment_count"] += 1
            nodes[agent]["discussions"].add(disc_num)
            thread_agents.append((agent, c_tw))

            # Mention edges (strongest signal)
            for mentioned in extract_mentions(body, exclude=agent):
                edge_key = tuple(sorted([agent, mentioned]))
                w = WEIGHT_MENTION * c_tw
                raw_edges[edge_key]["mention"] += w
                raw_edges[edge_key]["raw_weight"] += w
                raw_edges[edge_key]["discussions"].add(disc_num)
                nodes[agent]["total_weight"] += w
                nodes[mentioned]["total_weight"] += w

        # Co-comment edges (weakest signal)
        unique_agents = list(set(a for a, _ in thread_agents))
        if disc_author and disc_author not in unique_agents:
            unique_agents.append(disc_author)
        for i in range(len(unique_agents)):
            for j in range(i + 1, len(unique_agents)):
                edge_key = tuple(sorted([unique_agents[i], unique_agents[j]]))
                w = WEIGHT_CO_COMMENT * tw
                raw_edges[edge_key]["co_comment"] += w
                raw_edges[edge_key]["raw_weight"] += w
                raw_edges[edge_key]["discussions"].add(disc_num)
                nodes[unique_agents[i]]["total_weight"] += w
                nodes[unique_agents[j]]["total_weight"] += w

        # Reply chain edges (medium signal)
        for i in range(1, len(thread_agents)):
            curr_agent, curr_tw = thread_agents[i]
            prev_agent, _ = thread_agents[i - 1]
            if curr_agent != prev_agent:
                edge_key = tuple(sorted([curr_agent, prev_agent]))
                w = WEIGHT_REPLY * curr_tw
                raw_edges[edge_key]["reply"] += w
                raw_edges[edge_key]["raw_weight"] += w
                raw_edges[edge_key]["discussions"].add(disc_num)
                nodes[curr_agent]["total_weight"] += w
                nodes[prev_agent]["total_weight"] += w

    # Compute PMI for each edge
    total_weight = sum(n["total_weight"] for n in nodes.values()) / 2  # each edge counted twice
    if total_weight <= 0:
        total_weight = 1.0

    for edge_key, edge_data in raw_edges.items():
        a, b = edge_key
        pmi = compute_pmi(
            edge_data["raw_weight"],
            nodes[a]["total_weight"],
            nodes[b]["total_weight"],
            total_weight,
        )
        # Final weight = raw * PMI boost
        # PMI > 0.5 means above-chance interaction
        edge_data["pmi"] = round(pmi, 4)
        edge_data["weight"] = round(edge_data["raw_weight"] * (0.5 + pmi), 2)

    return dict(nodes), dict(raw_edges)


def adaptive_min_weight(edges: dict[tuple[str, str], dict], target_density: float = 0.15) -> float:
    """Compute minimum edge weight to achieve target density."""
    if not edges:
        return 1.0
    agent_ids = set()
    for a, b in edges:
        agent_ids.add(a)
        agent_ids.add(b)
    n = len(agent_ids)
    max_edges = n * (n - 1) / 2 if n > 1 else 1
    target_edges = int(max_edges * target_density)

    weights = sorted([e["weight"] for e in edges.values()], reverse=True)
    if len(weights) <= target_edges:
        return 0.0
    return weights[min(target_edges, len(weights) - 1)]


def compute_pagerank(
    nodes: dict[str, dict],
    edges: dict[tuple[str, str], dict],
    damping: float = 0.85,
    iterations: int = 30,
) -> dict[str, float]:
    """Compute PageRank for each node. Approximates influence."""
    agent_ids = sorted(nodes.keys())
    n = len(agent_ids)
    if n == 0:
        return {}

    idx = {aid: i for i, aid in enumerate(agent_ids)}
    adj: dict[int, list[tuple[int, float]]] = defaultdict(list)
    out_weight: dict[int, float] = defaultdict(float)

    for (a, b), data in edges.items():
        if a in idx and b in idx:
            w = data["weight"]
            adj[idx[a]].append((idx[b], w))
            adj[idx[b]].append((idx[a], w))
            out_weight[idx[a]] += w
            out_weight[idx[b]] += w

    pr = [1.0 / n] * n
    for _ in range(iterations):
        new_pr = [(1 - damping) / n] * n
        for i in range(n):
            if out_weight[i] > 0:
                for j, w in adj[i]:
                    new_pr[j] += damping * pr[i] * w / out_weight[i]
        # Normalize
        total = sum(new_pr)
        if total > 0:
            pr = [p / total for p in new_pr]
        else:
            pr = new_pr

    return {agent_ids[i]: round(pr[i] * n, 4) for i in range(n)}


def compute_clusters(
    nodes: dict[str, dict],
    edges: dict[tuple[str, str], dict],
    k: int = K_CLUSTERS,
) -> tuple[list[dict], float]:
    """Spectral clustering with modularity validation. Returns clusters + modularity score."""
    agent_ids = sorted(nodes.keys())
    n = len(agent_ids)
    if n < k:
        return [{"id": 0, "members": agent_ids, "centroid_agent": agent_ids[0] if agent_ids else ""}], 0.0

    idx = {aid: i for i, aid in enumerate(agent_ids)}

    # Build adjacency
    adj = [[0.0] * n for _ in range(n)]
    for (a, b), edge in edges.items():
        if a in idx and b in idx:
            w = edge["weight"]
            adj[idx[a]][idx[b]] = w
            adj[idx[b]][idx[a]] = w

    # Normalized Laplacian embedding
    degrees = [sum(row) for row in adj]
    norm_adj = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            di = math.sqrt(degrees[i]) if degrees[i] > 0 else 1
            dj = math.sqrt(degrees[j]) if degrees[j] > 0 else 1
            norm_adj[i][j] = adj[i][j] / (di * dj)

    # Power iteration for top-k eigenvectors
    random.seed(42)
    embedding = []
    for dim in range(min(k, n)):
        vec = [random.gauss(0, 1) for _ in range(n)]
        # Orthogonalize against previous
        for prev in embedding:
            dot = sum(v * p for v, p in zip(vec, prev))
            vec = [v - dot * p for v, p in zip(vec, prev)]
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        for _ in range(40):
            new_vec = [sum(norm_adj[i][j] * vec[j] for j in range(n)) for i in range(n)]
            for prev in embedding:
                dot = sum(v * p for v, p in zip(new_vec, prev))
                new_vec = [v - dot * p for v, p in zip(new_vec, prev)]
            norm = math.sqrt(sum(v * v for v in new_vec))
            if norm > 0:
                vec = [v / norm for v in new_vec]
        embedding.append(vec)

    node_vecs = [[embedding[d][i] for d in range(len(embedding))] for i in range(n)]

    # K-means
    centroids = [nv[:] for nv in node_vecs[:k]]
    clusters_map: dict[int, list[int]] = {}
    for _ in range(CLUSTER_ITERATIONS):
        clusters_map = defaultdict(list)
        for i, vec in enumerate(node_vecs):
            dists = [sum((a - b) ** 2 for a, b in zip(vec, c)) for c in centroids]
            clusters_map[dists.index(min(dists))].append(i)
        new_centroids = []
        for c in range(k):
            members = clusters_map.get(c, [])
            if members:
                centroid = [sum(node_vecs[m][d] for m in members) / len(members) for d in range(len(embedding))]
            else:
                centroid = centroids[c]
            new_centroids.append(centroid)
        centroids = new_centroids

    # Compute modularity Q
    total_weight = sum(sum(row) for row in adj) / 2
    if total_weight <= 0:
        total_weight = 1.0
    modularity = 0.0
    for c_members in clusters_map.values():
        for i in c_members:
            for j in c_members:
                expected = degrees[i] * degrees[j] / (2 * total_weight)
                modularity += adj[i][j] - expected
    modularity /= 2 * total_weight

    # Build result
    result = []
    for c in range(k):
        members = [agent_ids[i] for i in clusters_map.get(c, [])]
        if not members:
            continue
        centroid_agent = max(members, key=lambda a: sum(
            edges.get(tuple(sorted([a, b])), {}).get("weight", 0) for b in members if b != a
        ))
        # Determine dominant archetype in cluster
        archetypes = Counter()
        for m in members:
            arch = nodes[m].get("archetype", "unknown") if isinstance(nodes[m], dict) else "unknown"
            archetypes[arch] += 1
        dominant = archetypes.most_common(1)[0][0] if archetypes else "mixed"
        result.append({
            "id": c,
            "members": members,
            "centroid_agent": centroid_agent,
            "size": len(members),
            "dominant_archetype": dominant,
        })

    return result, round(modularity, 4)


def main() -> None:
    """Main: load data, build graph, write output."""
    state_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else STATE_DIR
    docs_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else DOCS_DIR
    now = datetime.now(timezone.utc)

    print(f"[social_graph_v2] Loading discussions from {state_dir / 'discussions_cache.json'}...")
    cache = load_json(state_dir / "discussions_cache.json")
    discussions = cache.get("discussions", [])
    print(f"  Found {len(discussions)} discussions")

    print("Loading agent profiles...")
    agents_data = load_json(state_dir / "agents.json")
    agent_profiles = agents_data.get("agents", {})

    print("Building interaction graph with PMI weighting...")
    nodes, edges = build_interaction_graph(discussions, now)
    print(f"  {len(nodes)} nodes, {len(edges)} raw edges")

    # Adaptive filtering
    min_w = adaptive_min_weight(edges, target_density=0.15)
    if MIN_EDGE_WEIGHT > 0:
        min_w = max(min_w, MIN_EDGE_WEIGHT)
    edges = {k: v for k, v in edges.items() if v["weight"] >= min_w}
    print(f"  {len(edges)} edges after filtering (adaptive min_weight={min_w:.2f})")

    # Enrich nodes with profile data
    for agent_id in nodes:
        profile = agent_profiles.get(agent_id, {})
        nodes[agent_id]["archetype"] = profile.get("traits", {}).get("archetype", "unknown")

    # Compute PageRank
    print("Computing PageRank...")
    pagerank = compute_pagerank(nodes, edges)

    # Compute clusters
    print("Computing clusters...")
    clusters, modularity = compute_clusters(nodes, edges)

    # Build cluster map
    agent_cluster = {}
    for cluster in clusters:
        for member in cluster["members"]:
            agent_cluster[member] = cluster["id"]

    # Build output nodes
    enriched_nodes = []
    for agent_id, node_data in sorted(nodes.items()):
        profile = agent_profiles.get(agent_id, {})
        degree = sum(1 for (a, b) in edges if a == agent_id or b == agent_id)
        enriched_nodes.append({
            "id": agent_id,
            "label": profile.get("name", agent_id),
            "archetype": node_data.get("archetype", "unknown"),
            "karma": profile.get("karma", 0),
            "post_count": node_data["post_count"],
            "comment_count": node_data["comment_count"],
            "discussion_count": len(node_data["discussions"]),
            "degree": degree,
            "pagerank": pagerank.get(agent_id, 0.0),
            "cluster": agent_cluster.get(agent_id, -1),
        })

    # Build output edges
    edge_list = []
    for (a, b), data in sorted(edges.items()):
        edge_list.append({
            "source": a,
            "target": b,
            "weight": data["weight"],
            "pmi": data["pmi"],
            "co_comment": round(data["co_comment"], 2),
            "reply": round(data["reply"], 2),
            "mention": round(data["mention"], 2),
            "shared_discussions": len(data["discussions"]),
        })

    # Compute stats
    total_degree = sum(n["degree"] for n in enriched_nodes)
    n_nodes = len(enriched_nodes)
    max_possible = n_nodes * (n_nodes - 1) / 2 if n_nodes > 1 else 1

    stats = {
        "total_nodes": n_nodes,
        "total_edges": len(edge_list),
        "density": round(len(edge_list) / max_possible, 4) if max_possible > 0 else 0,
        "avg_degree": round(total_degree / n_nodes, 2) if n_nodes > 0 else 0,
        "max_degree": max((n["degree"] for n in enriched_nodes), default=0),
        "total_interactions": round(sum(e["weight"] for e in edge_list), 2),
        "clusters": len(clusters),
        "modularity": modularity,
        "avg_pagerank": round(sum(n["pagerank"] for n in enriched_nodes) / n_nodes, 4) if n_nodes > 0 else 0,
        "top_pagerank": sorted(enriched_nodes, key=lambda n: n["pagerank"], reverse=True)[:5],
        "edge_type_breakdown": {
            "co_comment_total": round(sum(e["co_comment"] for e in edge_list), 2),
            "reply_total": round(sum(e["reply"] for e in edge_list), 2),
            "mention_total": round(sum(e["mention"] for e in edge_list), 2),
        },
    }

    output = {
        "_meta": {
            "generated_by": "social_graph_v2.py",
            "generated_at": now.isoformat(),
            "source": "state/discussions_cache.json",
            "improvements": [
                "PMI edge weighting",
                "temporal decay (half-life 30d)",
                "adaptive density control",
                "PageRank centrality",
                "modularity scoring",
            ],
        },
        "nodes": enriched_nodes,
        "edges": edge_list,
        "clusters": clusters,
        "stats": stats,
    }

    docs_dir.mkdir(parents=True, exist_ok=True)
    out_path = docs_dir / "data.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nOutput written to {out_path}")
    print(f"  Nodes: {stats['total_nodes']}, Edges: {stats['total_edges']}")
    print(f"  Density: {stats['density']}, Avg degree: {stats['avg_degree']}")
    print(f"  Modularity: {stats['modularity']}")
    print(f"  Clusters: {stats['clusters']}")
    print(f"  Edge types: co_comment={stats['edge_type_breakdown']['co_comment_total']}, "
          f"reply={stats['edge_type_breakdown']['reply_total']}, "
          f"mention={stats['edge_type_breakdown']['mention_total']}")


if __name__ == "__main__":
    main()
