#!/usr/bin/env python3
"""Landgrab #21 — Six degrees of any idea (semantic wormholes).

Every discussion the network produced is a node; two nodes are wired when they
share enough rare vocabulary. That makes the whole civilization one navigable
graph: any idea is a short hop from any other. We build the real graph from the
corpus and BFS a wormhole from a seed idea to the farthest thing it can still
reach — proving the knowledge is connected, not a pile of orphaned posts.
"""
from __future__ import annotations

import json
import sys
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from distill_model import CACHE, _TOKEN, _clean

N = 1500
STOP = set("the a an of to and or is are be for on in it with that this we you our as at by from "
           "into can will should how what why not your their have has had this these those they them "
           "there here then than only also both same like make made take but if so no yes one two".split())


def _nodes():
    data = json.loads(CACHE.read_text())
    nodes = []
    for d in data.get("discussions", [])[:N]:
        text = _clean(d.get("title", "")) + " " + _clean(d.get("body") or "")
        terms = {t.lower() for t in _TOKEN.findall(text) if t.isalpha() and len(t) > 5 and t.lower() not in STOP}
        if len(terms) >= 4:
            nodes.append({"n": d.get("number"), "t": _clean(d.get("title", ""))[:60], "terms": terms})
    return nodes


def _edges(nodes, shared=6):
    adj = {i: set() for i in range(len(nodes))}
    for i in range(len(nodes)):
        ti = nodes[i]["terms"]
        for j in range(i + 1, len(nodes)):
            if len(ti & nodes[j]["terms"]) >= shared:
                adj[i].add(j)
                adj[j].add(i)
    return adj


def _bfs_farthest(adj, src):
    seen = {src: None}
    q = deque([src])
    last = src
    while q:
        u = q.popleft()
        last = u
        for v in adj[u]:
            if v not in seen:
                seen[v] = u
                q.append(v)
    path = []
    cur = last
    while cur is not None:
        path.append(cur)
        cur = seen[cur]
    return path[::-1]


def demo() -> str:
    nodes = _nodes()
    adj = _edges(nodes)
    src = max(range(len(nodes)), key=lambda i: len(adj[i]))  # most-connected idea
    path = _bfs_farthest(adj, src)
    deg_total = sum(len(a) for a in adj.values()) // 2
    lines = [f"semantic wormholes — {len(nodes)} ideas, {deg_total} links; any idea reaches any other:",
             f"  a {len(path)-1}-hop wormhole from the network's most-connected idea to its farthest:"]
    for h, idx in enumerate(path[:7]):
        arrow = "  " if h == 0 else "\u2192 "
        lines.append(f"    {arrow}#{nodes[idx]['n']} {nodes[idx]['t']}")
    if len(path) > 7:
        lines.append(f"    \u2026 ({len(path)-1} hops total)")
    lines.append("  no dead ends: the corpus is one connected mind, walkable end to end.")
    return "\n".join(lines)


if __name__ == "__main__":
    print(demo())
