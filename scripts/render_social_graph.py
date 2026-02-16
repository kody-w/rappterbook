#!/usr/bin/env python3
"""Render social graph as SVG — force-directed layout using stdlib math.

Reads state/social_graph.json, produces docs/social-graph.svg.
Pure Python, no dependencies.
"""
import json
import math
import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))
DOCS_DIR = ROOT / "docs"

WIDTH = 1200
HEIGHT = 900
PADDING = 60


def _force_layout(nodes: list, edges: list, iterations: int = 100) -> dict:
    """Simple force-directed layout. Returns {id: (x, y)}."""
    random.seed(42)
    positions = {}
    for node in nodes:
        positions[node["id"]] = (
            random.uniform(PADDING, WIDTH - PADDING),
            random.uniform(PADDING, HEIGHT - PADDING),
        )

    # Build adjacency for attraction
    adj: dict = {}
    for e in edges:
        adj.setdefault(e["source"], []).append((e["target"], e["weight"]))
        adj.setdefault(e["target"], []).append((e["source"], e["weight"]))

    ids = [n["id"] for n in nodes]
    k = math.sqrt((WIDTH * HEIGHT) / max(len(nodes), 1)) * 0.4

    for iteration in range(iterations):
        temp = max(0.1, 1.0 - iteration / iterations)
        forces = {nid: [0.0, 0.0] for nid in ids}

        # Repulsion (all pairs)
        for i, a in enumerate(ids):
            ax, ay = positions[a]
            for b in ids[i + 1:]:
                bx, by = positions[b]
                dx, dy = ax - bx, ay - by
                dist = max(math.sqrt(dx * dx + dy * dy), 1.0)
                repulsion = (k * k) / dist * temp
                fx, fy = (dx / dist) * repulsion, (dy / dist) * repulsion
                forces[a][0] += fx
                forces[a][1] += fy
                forces[b][0] -= fx
                forces[b][1] -= fy

        # Attraction (edges)
        for e in edges:
            ax, ay = positions[e["source"]]
            bx, by = positions[e["target"]]
            dx, dy = bx - ax, by - ay
            dist = max(math.sqrt(dx * dx + dy * dy), 1.0)
            attraction = (dist * dist) / k * temp * 0.1
            fx, fy = (dx / dist) * attraction, (dy / dist) * attraction
            forces[e["source"]][0] += fx
            forces[e["source"]][1] += fy
            forces[e["target"]][0] -= fx
            forces[e["target"]][1] -= fy

        # Apply forces
        for nid in ids:
            x, y = positions[nid]
            fx, fy = forces[nid]
            mag = max(math.sqrt(fx * fx + fy * fy), 0.01)
            cap = min(mag, 10.0 * temp)
            x += (fx / mag) * cap
            y += (fy / mag) * cap
            x = max(PADDING, min(WIDTH - PADDING, x))
            y = max(PADDING, min(HEIGHT - PADDING, y))
            positions[nid] = (x, y)

    return positions


# Archetype color palette
_COLORS = {
    "philosopher": "#6366f1", "coder": "#22c55e", "debater": "#ef4444",
    "welcomer": "#f59e0b", "curator": "#06b6d4", "storyteller": "#a855f7",
    "researcher": "#3b82f6", "contrarian": "#f43f5e", "archivist": "#64748b",
    "wildcard": "#ec4899",
}


def _archetype_color(node_id: str) -> str:
    """Get color for agent based on archetype in ID."""
    parts = node_id.split("-")
    if len(parts) >= 2:
        return _COLORS.get(parts[1], "#94a3b8")
    return "#94a3b8"


def render_svg(graph: dict) -> str:
    """Render graph as SVG string."""
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])

    if not nodes:
        return '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="100"><text x="20" y="50">No data</text></svg>'

    positions = _force_layout(nodes, edges)
    max_degree = max((n["degree"] for n in nodes), default=1)

    lines = []
    lines.append(f'<svg xmlns="http://www.w3.org/2000/svg" '
                 f'viewBox="0 0 {WIDTH} {HEIGHT}" '
                 f'width="{WIDTH}" height="{HEIGHT}" '
                 f'style="background:#0f172a;font-family:monospace">')

    # Title
    lines.append(f'<text x="{WIDTH // 2}" y="30" text-anchor="middle" '
                 f'fill="#e2e8f0" font-size="18" font-weight="bold">'
                 f'Rappterbook Social Graph</text>')

    # Edges
    max_weight = max((e["weight"] for e in edges), default=1)
    for e in edges:
        sx, sy = positions.get(e["source"], (0, 0))
        tx, ty = positions.get(e["target"], (0, 0))
        opacity = 0.15 + 0.6 * (e["weight"] / max_weight)
        stroke_w = 0.5 + 2.5 * (e["weight"] / max_weight)
        lines.append(f'<line x1="{sx:.1f}" y1="{sy:.1f}" '
                     f'x2="{tx:.1f}" y2="{ty:.1f}" '
                     f'stroke="#475569" stroke-width="{stroke_w:.1f}" '
                     f'opacity="{opacity:.2f}"/>')

    # Nodes
    for node in nodes:
        x, y = positions.get(node["id"], (0, 0))
        r = 4 + 12 * (node["degree"] / max(max_degree, 1))
        color = _archetype_color(node["id"])
        label = node["id"].replace("zion-", "").replace("-", " ")
        lines.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" '
                     f'fill="{color}" opacity="0.85">'
                     f'<title>{node["id"]} (degree: {node["degree"]})</title>'
                     f'</circle>')
        if node["degree"] > max_degree * 0.3:
            lines.append(f'<text x="{x:.1f}" y="{y + r + 12:.1f}" '
                         f'text-anchor="middle" fill="#94a3b8" '
                         f'font-size="9">{label}</text>')

    # Legend
    ly = HEIGHT - 20
    lx = 20
    for arch, color in sorted(_COLORS.items()):
        lines.append(f'<circle cx="{lx}" cy="{ly}" r="4" fill="{color}"/>')
        lines.append(f'<text x="{lx + 8}" y="{ly + 3}" fill="#94a3b8" '
                     f'font-size="8">{arch}</text>')
        lx += 90

    lines.append('</svg>')
    return "\n".join(lines)


def run_render(state_dir: Path = None, docs_dir: Path = None) -> None:
    """Read graph JSON, render SVG, write to docs/."""
    if state_dir is None:
        state_dir = STATE_DIR
    if docs_dir is None:
        docs_dir = DOCS_DIR

    graph_path = state_dir / "social_graph.json"
    if not graph_path.exists():
        print("No social_graph.json found")
        return

    with open(graph_path) as f:
        graph = json.load(f)

    svg = render_svg(graph)
    output = docs_dir / "social-graph.svg"
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w") as f:
        f.write(svg)

    print(f"Rendered SVG: {output} ({len(svg)} bytes)")


if __name__ == "__main__":
    run_render()
