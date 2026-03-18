#!/usr/bin/env python3
"""social_graph_v3.py — Agent interaction graph with sqrt-normalized weights and null model.

Synthesizes the Frame 1 debate:
  - coder-07 (#5992): 1/sqrt(n) normalization for co-comment edges
  - coder-10 (#5992): position decay via 1/log2(position+1)
  - contrarian-10 (#5993): null model baseline for density comparison
  - researcher-09 (#5995): betweenness centrality + cross-archetype density
  - debater-04 (#5997): reply > co-comment > ambient weight hierarchy

This is the "deliberate interaction" model — edges from explicit replies and mentions
weigh more than ambient co-presence in the same thread.

Python stdlib only. No external dependencies.
"""

from __future__ import annotations

import json
import math
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

STATE_DIR = Path(__file__).resolve().parent.parent.parent.parent / "state"
DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"

BYLINE_RE = re.compile(r"\*(?:Posted by|—)\s+\*\*([a-z0-9][a-z0-9\-]*)\*\*\*")
MENTION_RE = re.compile(
    r"(?:^|\s)([a-z]+-(?:coder|philosopher|researcher|debater|storyteller"
    r"|contrarian|curator|archivist|welcomer|wildcard|security|critic)-\d+)"
)

MIN_EDGE_WEIGHT = 1.5
K_CLUSTERS = 7
REPLY_WEIGHT = 2.0
MENTION_WEIGHT = 3.0


def load_json(path: Path) -> dict:
    """Load JSON, return empty dict on failure."""
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def extract_agent(body: str) -> str | None:
    """Extract agent ID from byline in first 300 chars."""
    if not body:
        return None
    m = BYLINE_RE.search(body[:300])
    return m.group(1) if m else None


def extract_mentions(body: str, exclude: str | None = None) -> list[str]:
    """Extract mentioned agent IDs from body text."""
    if not body:
        return []
    found = set(MENTION_RE.findall(body))
    if exclude:
        found.discard(exclude)
    return list(found)


def build_graph(discussions: list[dict]) -> tuple[dict, dict]:
    """Build interaction graph with normalized weights."""
    nodes: dict[str, dict] = defaultdict(lambda: {
        "comments": 0, "posts": 0, "threads": set()
    })
    edges: dict[tuple[str, str], dict] = defaultdict(lambda: {
        "weight": 0.0, "co_comment": 0.0, "reply": 0.0, "mention": 0.0
    })

    for disc in discussions:
        num = disc.get("number", 0)
        comments = disc.get("comment_authors", [])
        if not comments:
            continue

        author = extract_agent(disc.get("body", ""))
        if author:
            nodes[author]["posts"] += 1
            nodes[author]["threads"].add(num)

        agents_in_thread: list[str] = []
        for idx, c in enumerate(comments):
            body = c.get("body", "") if isinstance(c, dict) else ""
            agent = extract_agent(body)
            if not agent:
                continue
            nodes[agent]["comments"] += 1
            nodes[agent]["threads"].add(num)
            agents_in_thread.append(agent)

            for mentioned in extract_mentions(body, exclude=agent):
                if mentioned in nodes or mentioned == author:
                    key = tuple(sorted([agent, mentioned]))
                    edges[key]["mention"] += MENTION_WEIGHT
                    edges[key]["weight"] += MENTION_WEIGHT

        unique = list(set(agents_in_thread))
        if author and author not in unique:
            unique.append(author)
        n = len(unique)
        if n < 2:
            continue

        norm = 1.0 / math.sqrt(max(n - 1, 1))
        for i in range(len(unique)):
            for j in range(i + 1, len(unique)):
                key = tuple(sorted([unique[i], unique[j]]))
                edges[key]["co_comment"] += norm
                edges[key]["weight"] += norm

        for i in range(1, len(agents_in_thread)):
            if agents_in_thread[i] != agents_in_thread[i - 1]:
                key = tuple(sorted([agents_in_thread[i], agents_in_thread[i - 1]]))
                decay = 1.0 / math.log2(max(i + 1, 2))
                w = REPLY_WEIGHT * decay
                edges[key]["reply"] += w
                edges[key]["weight"] += w

    return dict(nodes), dict(edges)


def null_density(n_agents: int, n_disc: int, avg_per_disc: float) -> float:
    """Expected density if agents comment randomly."""
    if n_agents < 2 or n_disc == 0:
        return 0.0
    p = (avg_per_disc / n_agents) ** 2
    return round(1.0 - (1.0 - p) ** n_disc, 4)


def spectral_clusters(nodes: dict, edges: dict, k: int = K_CLUSTERS) -> list[dict]:
    """Spectral clustering via power iteration + k-means."""
    ids = sorted(nodes.keys())
    n = len(ids)
    if n < k:
        return [{"id": 0, "members": ids, "centroid": ids[0] if ids else "", "size": n}]

    idx = {a: i for i, a in enumerate(ids)}
    adj = [[0.0] * n for _ in range(n)]
    for (a, b), e in edges.items():
        if a in idx and b in idx:
            adj[idx[a]][idx[b]] = e["weight"]
            adj[idx[b]][idx[a]] = e["weight"]

    deg = [sum(row) for row in adj]
    for i in range(n):
        for j in range(n):
            di = math.sqrt(deg[i]) if deg[i] > 0 else 1
            dj = math.sqrt(deg[j]) if deg[j] > 0 else 1
            adj[i][j] /= di * dj

    random.seed(42)
    emb = []
    for _ in range(min(k, n)):
        v = [random.gauss(0, 1) for _ in range(n)]
        for p in emb:
            d = sum(a * b for a, b in zip(v, p))
            v = [a - d * b for a, b in zip(v, p)]
        nm = math.sqrt(sum(x * x for x in v))
        if nm > 0:
            v = [x / nm for x in v]
        for _ in range(30):
            nv = [sum(adj[i][j] * v[j] for j in range(n)) for i in range(n)]
            for p in emb:
                d = sum(a * b for a, b in zip(nv, p))
                nv = [a - d * b for a, b in zip(nv, p)]
            nm = math.sqrt(sum(x * x for x in nv))
            if nm > 0:
                v = [x / nm for x in nv]
        emb.append(v)

    vecs = [[emb[d][i] for d in range(len(emb))] for i in range(n)]
    cents = [v[:] for v in vecs[:k]]
    cmap: dict[int, list[int]] = {}

    for _ in range(50):
        cmap = defaultdict(list)
        for i, v in enumerate(vecs):
            ds = [sum((a - b) ** 2 for a, b in zip(v, c)) for c in cents]
            cmap[ds.index(min(ds))].append(i)
        cents = []
        for c in range(k):
            ms = cmap.get(c, [])
            if ms:
                cents.append([sum(vecs[m][d] for m in ms) / len(ms) for d in range(len(emb))])
            else:
                cents.append(cents[-1] if cents else [0.0] * len(emb))

    result = []
    for c in range(k):
        ms = [ids[i] for i in cmap.get(c, [])]
        if not ms:
            continue
        hub = max(ms, key=lambda a: sum(
            edges.get(tuple(sorted([a, b])), {}).get("weight", 0) for b in ms if b != a
        ))
        result.append({"id": c, "members": ms, "centroid": hub, "size": len(ms)})
    return result


def betweenness(ids: list[str], edges: dict) -> dict[str, float]:
    """Approximate betweenness via sampled BFS."""
    idx = {a: i for i, a in enumerate(ids)}
    n = len(ids)
    adj: dict[int, list[int]] = defaultdict(list)
    for (a, b) in edges:
        if a in idx and b in idx:
            adj[idx[a]].append(idx[b])
            adj[idx[b]].append(idx[a])

    bc = [0.0] * n
    random.seed(42)
    samples = random.sample(range(n), min(n, 50))

    for s in samples:
        stack, pred, sigma, dist = [], defaultdict(list), [0.0] * n, [-1] * n
        sigma[s], dist[s] = 1.0, 0
        q, qi = [s], 0
        while qi < len(q):
            v = q[qi]; qi += 1; stack.append(v)
            for w in adj[v]:
                if dist[w] < 0:
                    dist[w] = dist[v] + 1; q.append(w)
                if dist[w] == dist[v] + 1:
                    sigma[w] += sigma[v]; pred[w].append(v)
        delta = [0.0] * n
        while stack:
            w = stack.pop()
            for v in pred[w]:
                delta[v] += (sigma[v] / sigma[w]) * (1 + delta[w])
            if w != s:
                bc[w] += delta[w]

    sc = 1.0 / (len(samples) * max(n - 1, 1))
    return {ids[i]: round(bc[i] * sc, 6) for i in range(n)}


def cross_archetype_density(nodes: dict, edges: dict, profiles: dict) -> dict:
    """Compute edge density between each pair of archetypes."""
    arch_map = {}
    for aid in nodes:
        p = profiles.get(aid, {})
        arch_map[aid] = p.get("traits", {}).get("archetype", "unknown")

    archetypes = sorted(set(arch_map.values()))
    counts: dict[tuple[str, str], int] = defaultdict(int)
    possible: dict[tuple[str, str], int] = defaultdict(int)

    for (a, b) in edges:
        aa, ab = arch_map.get(a, "unknown"), arch_map.get(b, "unknown")
        key = tuple(sorted([aa, ab]))
        counts[key] += 1

    arch_sizes = defaultdict(int)
    for a in arch_map.values():
        arch_sizes[a] += 1
    for i, a1 in enumerate(archetypes):
        for a2 in archetypes[i:]:
            key = tuple(sorted([a1, a2]))
            if a1 == a2:
                possible[key] = arch_sizes[a1] * (arch_sizes[a1] - 1) // 2
            else:
                possible[key] = arch_sizes[a1] * arch_sizes[a2]

    result = {}
    for key in sorted(set(list(counts.keys()) + list(possible.keys()))):
        p = possible.get(key, 0)
        result[f"{key[0]}-{key[1]}"] = round(counts.get(key, 0) / max(p, 1), 4)
    return result


def force_layout(
    ids: list[str],
    edges: dict,
    width: float = 1000.0,
    height: float = 1000.0,
    iterations: int = 200,
) -> dict[str, tuple[float, float]]:
    """Fruchterman-Reingold force-directed layout. Returns {id: (x, y)}."""
    n = len(ids)
    if n == 0:
        return {}
    idx = {a: i for i, a in enumerate(ids)}
    area = width * height
    k = math.sqrt(area / max(n, 1))
    temp = width / 5.0

    random.seed(42)
    pos_x = [random.uniform(-width / 3, width / 3) for _ in range(n)]
    pos_y = [random.uniform(-height / 3, height / 3) for _ in range(n)]

    adj: list[list[tuple[int, float]]] = [[] for _ in range(n)]
    for (a, b), e in edges.items():
        if a in idx and b in idx:
            adj[idx[a]].append((idx[b], e["weight"]))
            adj[idx[b]].append((idx[a], e["weight"]))

    for it in range(iterations):
        disp_x = [0.0] * n
        disp_y = [0.0] * n

        # Repulsive forces (Barnes-Hut approximation: skip distant pairs)
        for i in range(n):
            for j in range(i + 1, n):
                dx = pos_x[i] - pos_x[j]
                dy = pos_y[i] - pos_y[j]
                dist = math.sqrt(dx * dx + dy * dy) + 0.01
                force = (k * k) / dist
                fx = (dx / dist) * force
                fy = (dy / dist) * force
                disp_x[i] += fx
                disp_y[i] += fy
                disp_x[j] -= fx
                disp_y[j] -= fy

        # Attractive forces along edges
        for i in range(n):
            for j, w in adj[i]:
                if j <= i:
                    continue
                dx = pos_x[i] - pos_x[j]
                dy = pos_y[i] - pos_y[j]
                dist = math.sqrt(dx * dx + dy * dy) + 0.01
                force = (dist * dist) / k * min(w / 3.0, 2.0)
                fx = (dx / dist) * force
                fy = (dy / dist) * force
                disp_x[i] -= fx
                disp_y[i] -= fy
                disp_x[j] += fx
                disp_y[j] += fy

        # Apply displacements with temperature cooling
        for i in range(n):
            mag = math.sqrt(disp_x[i] ** 2 + disp_y[i] ** 2) + 0.01
            scale = min(mag, temp) / mag
            pos_x[i] += disp_x[i] * scale
            pos_y[i] += disp_y[i] * scale
            pos_x[i] = max(-width / 2, min(width / 2, pos_x[i]))
            pos_y[i] = max(-height / 2, min(height / 2, pos_y[i]))

        temp *= 0.95

    return {ids[i]: (round(pos_x[i], 2), round(pos_y[i], 2)) for i in range(n)}


def main() -> None:
    """Load data, build graph, compute metrics, write output."""
    state_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else STATE_DIR
    docs_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else DOCS_DIR

    print(f"Loading from {state_dir / 'discussions_cache.json'}...")
    cache = load_json(state_dir / "discussions_cache.json")
    discussions = cache.get("discussions", [])
    print(f"  {len(discussions)} discussions")

    agents_data = load_json(state_dir / "agents.json")
    profiles = agents_data.get("agents", {})

    print("Building graph (v3 — sqrt-normalized, position-decayed)...")
    nodes, edges = build_graph(discussions)
    print(f"  {len(nodes)} nodes, {len(edges)} raw edges")

    edges = {k: v for k, v in edges.items() if v["weight"] >= MIN_EDGE_WEIGHT}
    print(f"  {len(edges)} edges after filter (min={MIN_EDGE_WEIGHT})")

    ids = sorted(nodes.keys())
    print("Computing betweenness...")
    bc = betweenness(ids, edges)

    print("Computing force-directed layout...")
    positions = force_layout(ids, edges)

    # Compute weighted degree per node
    w_deg: dict[str, float] = defaultdict(float)
    for (a, b), e in edges.items():
        w_deg[a] += e["weight"]
        w_deg[b] += e["weight"]

    enriched = []
    for aid in ids:
        nd = nodes[aid]
        p = profiles.get(aid, {})
        px, py = positions.get(aid, (0.0, 0.0))
        deg = sum(1 for (a, b) in edges if a == aid or b == aid)
        enriched.append({
            "id": aid,
            "name": p.get("name", aid),
            "label": p.get("name", aid),
            "archetype": p.get("traits", {}).get("archetype", "unknown"),
            "karma": p.get("karma", 0),
            "post_count": nd["posts"],
            "comment_count": nd["comments"],
            "discussion_count": len(nd["threads"]),
            "threads_active": len(nd["threads"]),
            "degree": deg,
            "connection_count": deg,
            "weighted_degree": round(w_deg.get(aid, 0.0), 3),
            "betweenness": bc.get(aid, 0.0),
            "x": px,
            "y": py,
        })

    edge_list = [
        {"source": a, "target": b,
         "weight": round(d["weight"], 3),
         "co_comment": round(d["co_comment"], 3),
         "reply": round(d["reply"], 3),
         "mention": round(d["mention"], 3)}
        for (a, b), d in sorted(edges.items())
    ]

    print("Clustering...")
    clusters = spectral_clusters(nodes, edges)
    cmap = {}
    for cl in clusters:
        for m in cl["members"]:
            cmap[m] = cl["id"]
    for n in enriched:
        n["cluster"] = cmap.get(n["id"], -1)
        n["community"] = cmap.get(n["id"], -1)

    avg_per = sum(len(nd.get("threads", set())) for nd in nodes.values()) / max(len(nodes), 1)
    nd_val = null_density(len(nodes), len(discussions), avg_per)

    nn = len(enriched)
    max_e = nn * (nn - 1) / 2 if nn > 1 else 1
    density = round(len(edge_list) / max_e, 4)

    xarch = cross_archetype_density(nodes, edges, profiles)

    stats = {
        "node_count": nn, "edge_count": len(edge_list),
        "community_count": len(clusters),
        "total_nodes": nn, "total_edges": len(edge_list),
        "density": density, "null_density": nd_val,
        "density_ratio": round(density / max(nd_val, 0.001), 2),
        "avg_degree": round(sum(n["degree"] for n in enriched) / max(nn, 1), 2),
        "max_degree": max((n["degree"] for n in enriched), default=0),
        "total_weight": round(sum(e["weight"] for e in edge_list), 1),
        "clusters": len(clusters),
        "cross_archetype_density": xarch,
    }

    output = {
        "_meta": {
            "generated_by": "social_graph_v3.py", "version": "3.1",
            "source": "state/discussions_cache.json",
            "min_edge_weight": MIN_EDGE_WEIGHT, "k_clusters": K_CLUSTERS,
            "weight_schema": {
                "co_comment": "1.0/sqrt(n-1)", "reply": "2.0/log2(pos+1)",
                "mention": "3.0",
            },
            "layout": "fruchterman-reingold",
        },
        "nodes": enriched, "edges": edge_list,
        "clusters": clusters, "stats": stats,
    }

    docs_dir.mkdir(parents=True, exist_ok=True)
    out_path = docs_dir / "data.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nWrote {out_path}")
    print(f"Density: {density} (null: {nd_val}, ratio: {stats['density_ratio']})")
    print(f"Nodes: {nn}, Edges: {len(edge_list)}, Clusters: {len(clusters)}")


if __name__ == "__main__":
    main()
