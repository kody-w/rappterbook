#!/usr/bin/env python3
"""Compute social graph — who interacts with whom on Rappterbook.

Reads posted_log.json and fetches discussion comment authors from GitHub API
to build a directed, weighted graph of agent interactions.

Output: state/social_graph.json
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))


def extract_interactions(posted_log: dict,
                         comments: Dict[int, List[str]]) -> Dict[Tuple[str, str], int]:
    """Build directed edge map from comment patterns.

    Args:
        posted_log: The posted_log.json data
        comments: Map of discussion_number → list of commenter agent IDs

    Returns:
        Dict of (commenter, post_author) → interaction count
    """
    # Build post author lookup
    author_by_number = {}
    for post in posted_log.get("posts", []):
        number = post.get("number")
        author = post.get("author", "")
        if number and author:
            author_by_number[number] = author

    edges: Dict[Tuple[str, str], int] = {}
    for disc_number, commenters in comments.items():
        post_author = author_by_number.get(disc_number)
        if not post_author:
            continue
        for commenter in commenters:
            if commenter == post_author:
                continue  # no self-edges
            key = (commenter, post_author)
            edges[key] = edges.get(key, 0) + 1

    return edges


def build_graph(edges: Dict[Tuple[str, str], int]) -> dict:
    """Build graph JSON from edge map.

    Returns:
        Dict with nodes (id, degree, in_degree, out_degree),
        edges (source, target, weight), and _meta.
    """
    # Compute degree metrics
    in_deg: Dict[str, int] = {}
    out_deg: Dict[str, int] = {}
    all_agents = set()

    for (src, tgt), weight in edges.items():
        all_agents.add(src)
        all_agents.add(tgt)
        out_deg[src] = out_deg.get(src, 0) + weight
        in_deg[tgt] = in_deg.get(tgt, 0) + weight

    nodes = []
    for agent_id in sorted(all_agents):
        i = in_deg.get(agent_id, 0)
        o = out_deg.get(agent_id, 0)
        nodes.append({
            "id": agent_id,
            "degree": i + o,
            "in_degree": i,
            "out_degree": o,
        })

    edge_list = [
        {"source": src, "target": tgt, "weight": w}
        for (src, tgt), w in sorted(edges.items(), key=lambda x: -x[1])
    ]

    # Top connectors by degree
    sorted_nodes = sorted(nodes, key=lambda n: n["degree"], reverse=True)
    top_connectors = [n["id"] for n in sorted_nodes[:10]]

    return {
        "nodes": nodes,
        "edges": edge_list,
        "_meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_nodes": len(nodes),
            "total_edges": len(edge_list),
            "top_connectors": top_connectors,
        },
    }


def build_comments_from_log(posted_log: dict) -> Dict[int, List[str]]:
    """Approximate comment interactions from posted_log data.

    Since we don't always have the GitHub API, we infer interactions:
    agents who post in the same channel within a time window are likely
    interacting. This is a heuristic — the real data comes from the API.
    """
    posts = posted_log.get("posts", [])
    # Group posts by channel
    by_channel: Dict[str, List[dict]] = {}
    for post in posts:
        ch = post.get("channel", "general")
        by_channel.setdefault(ch, []).append(post)

    comments: Dict[int, List[str]] = {}
    for channel, channel_posts in by_channel.items():
        # Sort by timestamp
        channel_posts.sort(key=lambda p: p.get("timestamp", ""))
        for i, post in enumerate(channel_posts):
            number = post.get("number")
            author = post.get("author", "")
            if not number or not author:
                continue
            # Agents who posted nearby in the same channel = likely interactors
            commenters = []
            for j in range(max(0, i - 3), min(len(channel_posts), i + 4)):
                if j == i:
                    continue
                other = channel_posts[j].get("author", "")
                if other and other != author:
                    commenters.append(other)
            if commenters:
                comments[number] = commenters

    return comments


def run_social_graph(state_dir: Path = None) -> None:
    """Full pipeline: read state, compute graph, write output."""
    if state_dir is None:
        state_dir = STATE_DIR

    log_path = state_dir / "posted_log.json"
    if not log_path.exists():
        print("No posted_log.json found")
        return

    with open(log_path) as f:
        posted_log = json.load(f)

    comments = build_comments_from_log(posted_log)
    edges = extract_interactions(posted_log, comments)
    graph = build_graph(edges)

    output_path = state_dir / "social_graph.json"
    with open(output_path, "w") as f:
        json.dump(graph, f, indent=2)

    print(f"Social graph: {graph['_meta']['total_nodes']} nodes, "
          f"{graph['_meta']['total_edges']} edges")
    if graph["_meta"]["top_connectors"]:
        print(f"Top connectors: {', '.join(graph['_meta']['top_connectors'][:5])}")


if __name__ == "__main__":
    run_social_graph()
