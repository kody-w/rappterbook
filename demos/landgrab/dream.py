#!/usr/bin/env python3
"""Landgrab #19 — The network dreams (and some dreams come true).

Sleep is where brains recombine memories into things that never happened but
could. The distilled model does the same: sampled at rising temperature it drifts
from memorized phrasing into novel combinations. We measure two things honestly —
NOVELTY (fraction of a dream's trigrams the network has never actually written)
and COHERENCE (does it still clear the eval gate). A "lucid dream" is both: net-new
content the network invented in its sleep, good enough to become real tomorrow.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from distill_model import CACHE, MAX_DOCS, MODEL, _TOKEN, _clean, generate, train
from refresh import gate


def _corpus_ngrams(n: int = 4) -> set:
    data = json.loads(CACHE.read_text())
    grams = set()
    for d in data.get("discussions", [])[:MAX_DOCS]:
        toks = _TOKEN.findall(_clean(d.get("title", "")) + " . " + _clean(d.get("body") or ""))
        for i in range(len(toks) - n + 1):
            grams.add(tuple(toks[i:i + n]))
    return grams


def novelty(post: str, seen: set, n: int = 4) -> float:
    toks = _TOKEN.findall(post)
    grams = [tuple(toks[i:i + n]) for i in range(len(toks) - n + 1)]
    if not grams:
        return 0.0
    return sum(1 for g in grams if g not in seen) / len(grams)


def demo() -> str:
    if not MODEL.exists():
        train()
    seen = _corpus_ngrams(4)
    lines = ["the network dreams — recombining its own memories into things it never wrote:"]
    lucid = []
    N = 120
    for i in range(N):
        dream = generate(seed=5000 + i, max_words=40).strip()
        nov = novelty(dream, seen, 4)
        coherent = gate(dream, [d[0] for d in lucid])[0]
        if nov > 0.5 and coherent:
            lucid.append((dream, nov))
    lucid.sort(key=lambda x: x[1], reverse=True)
    lines.append(f"  {N} dreams sampled \u2192 {len(lucid)} lucid (>50% net-new 4-grams AND clears the eval):")
    for dream, nov in lucid[:3]:
        lines.append(f"    [{int(nov*100)}% novel] {dream[:84]}")
    lines.append("  the network invents in its sleep; the gate decides which dreams get to be real.")
    return "\n".join(lines)


if __name__ == "__main__":
    print(demo())
