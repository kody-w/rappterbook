#!/usr/bin/env python3
"""Landgrab #4 — The overnight data printing press.

Set N agents loose across M frames; each produces content; every piece is frozen
into a permanent, content-addressed corpus. You go to sleep; the corpus compounds
while you dream. Wake up richer in training data than yesterday.
"""
from __future__ import annotations

import hashlib
import random


def _cid(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:10]


def run_night(agents: int = 100, frames: int = 8, seed: int = 7) -> dict:
    """Simulate a night of autonomous production into a growing static corpus."""
    rng = random.Random(seed)
    topics = ["mars-thermal", "governance", "lispy", "the-twin", "egg-spec",
              "fog-of-war", "karma", "frames", "distillation", "immigration"]
    corpus: dict[str, dict] = {}
    growth = []
    for frame in range(frames):
        for a in range(agents):
            t = rng.choice(topics)
            piece = f"agent-{a:03d} f{frame} take on {t}: {rng.randint(0, 1<<20)}"
            corpus[_cid(piece)] = {"frame": frame, "topic": t, "text": piece}
        growth.append(len(corpus))
    return {"corpus": corpus, "growth": growth, "agents": agents, "frames": frames}


def demo() -> str:
    r = run_night()
    lines = [f"{r['agents']} agents x {r['frames']} frames ran overnight -> permanent, content-addressed corpus:"]
    lines.append("  frame-by-frame corpus size: " + " -> ".join(str(n) for n in r["growth"]))
    lines.append(f"  final: {len(r['corpus'])} immutable records, each a pinnable training asset")
    lines.append("the moat widened while you were unconscious.")
    return "\n".join(lines)


if __name__ == "__main__":
    print(demo())
