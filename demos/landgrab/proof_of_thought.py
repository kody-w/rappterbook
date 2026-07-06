#!/usr/bin/env python3
"""Landgrab #13 — Mine ideas like bitcoin, but the work is intelligence.

Proof-of-Thought: a record is only "mined" when it clears TWO bars at once —
(1) it passes the eval gate (real, on-brand, non-slop content) and (2) a nonce
makes its hash meet a difficulty target. Bitcoin burns electricity to prove
nothing; Proof-of-Thought burns it to prove a genuinely good idea was produced.
Anyone can verify a block in one hash. Scarcity, minted from cognition.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from distill_model import MODEL, generate, train
from refresh import gate


def mine(difficulty: int = 3, tries_per_post: int = 200000, seed_base: int = 7000):
    """Find a post that clears the eval AND whose hash meets the target."""
    if not MODEL.exists():
        train()
    target = "0" * difficulty
    recent: list[str] = []
    seed = seed_base
    while True:
        post = generate(seed=seed, max_words=44).strip()
        seed += 1
        ok, _ = gate(post, recent)
        if not ok:
            continue
        for nonce in range(tries_per_post):
            h = hashlib.sha256(f"{post}|{nonce}".encode()).hexdigest()
            if h.startswith(target):
                recent.append(post)
                return {"post": post, "nonce": nonce, "hash": h,
                        "difficulty": difficulty, "seed": seed - 1}
        # no nonce found in budget -> try the next thought


def verify(block) -> bool:
    """One-hash verification anyone can run: gate pass AND difficulty met."""
    ok, _ = gate(block["post"], [])
    h = hashlib.sha256(f"{block['post']}|{block['nonce']}".encode()).hexdigest()
    return ok and h == block["hash"] and h.startswith("0" * block["difficulty"])


def demo() -> str:
    lines = ["proof-of-thought — a block is valid only if it is BOTH a good idea AND hard to forge:"]
    for d in (2, 3):
        b = mine(difficulty=d, seed_base=7000 + d * 1000)
        lines.append(f"  difficulty {d}: nonce {b['nonce']:>6} -> hash {b['hash'][:18]}\u2026 "
                     f"(verify={verify(b)})")
        lines.append(f"    minted idea: {b['post'][:88]}")
    lines.append("  the proof-of-work IS the intelligence: no gated idea, no block. verify in one hash.")
    return "\n".join(lines)


if __name__ == "__main__":
    print(demo())
