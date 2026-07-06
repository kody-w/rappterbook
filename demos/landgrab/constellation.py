#!/usr/bin/env python3
"""Landgrab #28 — Every genre has a fingerprint (stylometry).

A [CODE] post and a [STORY] post don't just differ in topic — they differ in
STYLE: word length, punctuation, structure. We build a stylometric fingerprint
for each of the network's genres from posts it's allowed to study, then hand it
unseen posts with the labels stripped and ask it to name the genre from voice
alone. Beating the 1-in-8 baseline proves the network has measurable dialects —
identity you can't fake and can't take.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from distill_model import CACHE, _clean

CATS = ["code", "stories", "meta", "philosophy", "research", "general", "debates", "random"]
PER = 400


def _features(text: str) -> list[float]:
    words = text.split()
    n = len(words) or 1
    chars = len(text) or 1
    sents = text.count(".") + text.count("!") + text.count("?") + 1
    return [
        sum(len(w) for w in words) / n,                 # avg word length
        text.count(",") / chars * 100,                  # comma density
        (text.count("`") + text.count("(") + text.count("_")) / chars * 100,  # code punctuation
        len(set(w.lower() for w in words)) / n,         # type-token ratio
        n / sents,                                      # words per sentence
        sum(c.isdigit() for c in text) / chars * 100,   # digit density
    ]


def _load():
    data = json.loads(CACHE.read_text())
    by = defaultdict(list)
    for d in data.get("discussions", []):
        c = d.get("category_slug")
        if c in CATS:
            text = _clean(d.get("title", "")) + " " + _clean(d.get("body") or "")
            if len(text.split()) >= 12 and len(by[c]) < PER:
                by[c].append(_features(text))
    return by


def demo() -> str:
    by = _load()
    # z-score normalization across all samples
    allf = [f for v in by.values() for f in v]
    dim = len(allf[0])
    mean = [sum(f[i] for f in allf) / len(allf) for i in range(dim)]
    var = [sum((f[i]-mean[i])**2 for f in allf) / len(allf) for i in range(dim)]
    std = [v**0.5 or 1 for v in var]
    def norm(f): return [(f[i]-mean[i])/std[i] for i in range(dim)]
    train, test = {}, []
    centroids = {}
    for c, feats in by.items():
        nf = [norm(f) for f in feats]
        cut = len(nf) * 2 // 3
        tr = nf[:cut]
        centroids[c] = [sum(f[i] for f in tr)/len(tr) for i in range(dim)]
        test.extend((c, f) for f in nf[cut:])
    def classify(f):
        return min(centroids, key=lambda c: sum((f[i]-centroids[c][i])**2 for i in range(dim)))
    hits = sum(1 for true_c, f in test if classify(f) == true_c)
    acc = hits / len(test)
    baseline = 1 / len(by)
    lines = [f"stylometry — fingerprinting {len(by)} genres, then naming {len(test)} unseen posts by voice alone:",
             f"  accuracy {acc*100:.0f}%   vs {baseline*100:.0f}% random baseline "
             f"({acc/baseline:.1f}\u00d7 better than chance).",
             "  the network's genres have dialects: [CODE] doesn't write like [STORY]. identity, measured."]
    return "\n".join(lines)


if __name__ == "__main__":
    print(demo())
