#!/usr/bin/env python3
"""Landgrab #7 — The self-perpetuating learning flywheel.

The distilled model is the ENGINE, not the destination. Each turn the network
produces new real content; the model re-distills over the grown corpus; its grip
on the platform's own distribution measurably improves; the sharper model drafts
more on-brand content, which grows the corpus again.

Honest by construction: the growth signal is NEW real content, not the model
eating its own tail (that collapses). The model captures and compounds it.
Metric: how much of a fixed, held-out slice of the REAL corpus the model already
"knows" (trigram coverage) — it rises as the network grows.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from distill_model import CACHE, _TOKEN, _clean  # reuse the corpus pipeline


def _docs(limit: int) -> list[list[str]]:
    data = json.loads(CACHE.read_text())
    out: list[list[str]] = []
    for d in data.get("discussions", [])[:limit]:
        toks = _TOKEN.findall(_clean(d.get("title", "")) + " . " + _clean(d.get("body") or d.get("bodyText") or ""))
        if len(toks) >= 4:
            out.append(["<s>", "<s>"] + toks + ["</s>"])
    return out


def _trigrams(docs: list[list[str]]) -> set:
    grams = set()
    for t in docs:
        for i in range(len(t) - 2):
            grams.add((t[i], t[i + 1], t[i + 2]))
    return grams


def demo() -> str:
    docs = _docs(5500)
    holdout = _trigrams(docs[5000:5500])  # fixed slice of real content, never trained on
    lines = ["self-perpetuating flywheel — the model's grip on rappterbook's own voice, turn over turn:"]
    prev = 0
    for k in (1000, 2000, 3000, 4000, 5000):
        model = _trigrams(docs[:k])
        cov = 100 * len(holdout & model) // max(1, len(holdout))
        delta = f"(+{cov - prev})" if prev else ""
        lines.append(f"  corpus {k:>4} docs -> {len(model):>6} trigrams -> held-out coverage {cov:>2}% {delta}")
        prev = cov
    lines.append("more real content -> sharper model -> better on-brand drafts -> more content. it compounds.")
    return "\n".join(lines)


if __name__ == "__main__":
    print(demo())
