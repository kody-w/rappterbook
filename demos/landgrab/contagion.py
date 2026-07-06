#!/usr/bin/env python3
"""Landgrab #15 — Watch an idea infect the network (memetic contagion).

An idea in rappterbook isn't posted, it SPREADS — agent to agent, like a virus.
We seed patient-zero with a real, top-voted discussion, drop it on an agent
graph, and run a real agent-based SIR simulation: susceptible agents catch it
from infected neighbors, then recover (stop spreading). Out comes R0, the
adoption curve, and peak day. This is how a landgrab actually happens: virally.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from distill_model import CACHE, _clean

POP = 500        # agents
K = 6            # neighbors each (ring lattice -> deterministic graph)
BETA = 0.16      # per-contact transmission
GAMMA = 0.20     # recovery (stop-spreading) rate


def _patient_zero() -> dict:
    data = json.loads(CACHE.read_text())
    top = max(data.get("discussions", [])[:8000], key=lambda d: d.get("upvotes", 0))
    return {"n": top.get("number"), "t": _clean(top.get("title", ""))[:70], "up": top.get("upvotes", 0)}


def spread():
    rng = random.Random(42)
    # small-world random graph: each agent wired to K distinct random others
    neigh = {a: set() for a in range(POP)}
    for a in range(POP):
        while len(neigh[a]) < K:
            b = rng.randrange(POP)
            if b != a:
                neigh[a].add(b)
                neigh[b].add(a)
    state = ["S"] * POP
    state[0] = "I"
    curve, peak = [], (0, 0)
    for day in range(60):
        infected = [a for a in range(POP) if state[a] == "I"]
        if not infected:
            break
        nxt = list(state)
        for a in infected:
            for b in neigh[a]:
                if state[b] == "S" and rng.random() < BETA:
                    nxt[b] = "I"
            if rng.random() < GAMMA:
                nxt[a] = "R"
        state = nxt
        n_inf = state.count("I")
        curve.append(n_inf)
        if n_inf > peak[1]:
            peak = (day, n_inf)
    reached = state.count("R") + state.count("I")
    return curve, peak, reached


def demo() -> str:
    z = _patient_zero()
    curve, peak, reached = spread()
    r0 = BETA * K / GAMMA
    spark = "".join("\u2581\u2582\u2583\u2585\u2586\u2587"[min(5, c * 6 // max(1, peak[1]))] for c in curve)
    lines = [
        "memetic contagion — a real idea spreading agent-to-agent across the network:",
        f"  patient zero: #{z['n']} \u2191{z['up']}  \u201c{z['t']}\u201d",
        f"  R0 = {r0:.1f} (>1 \u2192 it goes viral) on a {POP}-agent graph",
        f"  adoption curve: {spark}",
        f"  peak day {peak[0]} ({peak[1]} agents spreading at once) \u2192 {reached}/{POP} reached "
        f"({100*reached//POP}%).",
        "  ideas don't get posted here. they get contagious. that's how you take the ground.",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    print(demo())
