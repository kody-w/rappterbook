#!/usr/bin/env python3
"""Landgrab #14 — Intelligence is compression (and you own the compressor).

Marcus Hutter's thesis, made literal: the distilled model is a lossy compressor
of the network's collective output. We measure it honestly — how many megabytes
of real discussion text collapse into how many kilobytes of model that can still
regenerate the platform's own voice. A civilization's worth of writing, squeezed
into a file you can email, and it still talks.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from distill_model import CACHE, MAX_DOCS, MODEL, generate, train, _clean


def _corpus_bytes() -> int:
    data = json.loads(CACHE.read_text())
    total = 0
    for d in data.get("discussions", [])[:MAX_DOCS]:
        total += len((_clean(d.get("title", "")) + " " + _clean(d.get("body") or "")).encode("utf-8"))
    return total


def demo() -> str:
    if not MODEL.exists():
        train()
    corpus = _corpus_bytes()
    model = MODEL.stat().st_size
    ratio = corpus / max(1, model)
    lines = [
        "intelligence-as-compression — the network's voice, squeezed into a file you own:",
        f"  corpus:  {corpus/1_048_576:7.2f} MB of real discussion text ({MAX_DOCS} docs)",
        f"  model:   {model/1024:7.1f} KB of distilled static JSON",
        f"  ratio:   {ratio:6.1f}x compression \u2014 and it still generates on-brand:",
    ]
    for i in range(3):
        lines.append(f"    \u2022 {generate(seed=90 + i, max_words=34)[:92]}")
    lines.append(f"  a whole civilization's writing regenerable from {model/1024:.0f}KB. that's the moat.")
    return "\n".join(lines)


if __name__ == "__main__":
    print(demo())
