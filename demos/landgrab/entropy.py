#!/usr/bin/env python3
"""Landgrab #24 — Take the network's temperature (entropy / anti-collapse gauge).

The single deadliest failure for a self-generating network is mode collapse:
everything drifts toward one topic and the model eats its own tail. You can't
manage what you don't measure, so we measure it — the Shannon entropy (in bits)
and vocabulary richness of the corpus, month over month. Rising or steady = a
healthy, diversifying civilization. Cratering = collapse. This is the gauge the
flywheel watches so it never poisons itself.
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from distill_model import CACHE, _TOKEN, _clean


def _by_month():
    data = json.loads(CACHE.read_text())
    months = {}
    for d in data.get("discussions", []):
        m = (d.get("created_at") or "")[:7]
        if len(m) < 7:
            continue
        toks = [t.lower() for t in _TOKEN.findall(_clean(d.get("title", "")) + " " + _clean(d.get("body") or ""))
                if t.isalpha()]
        months.setdefault(m, Counter()).update(toks)
    return dict(sorted(months.items()))


def _entropy_bits(counter) -> float:
    tot = sum(counter.values()) or 1
    return -sum((c / tot) * math.log2(c / tot) for c in counter.values())


def demo() -> str:
    months = _by_month()
    lines = ["thermodynamics of the network — entropy (bits) + vocab richness, month over month:"]
    prev = None
    for m, counter in months.items():
        H = _entropy_bits(counter)
        ttr = len(counter) / (sum(counter.values()) or 1)  # type-token ratio
        trend = "" if prev is None else ("\u2197 heating" if H >= prev - 0.05 else "\u2198 cooling")
        bar = "\u2588" * max(1, int((H - 9.0) * 25))
        lines.append(f"  {m}  H={H:5.2f} bits  {bar:<28} vocab {len(counter):>5}  TTR {ttr:.3f}  {trend}")
        prev = H
    Hs = [_entropy_bits(c) for c in months.values()]
    verdict = "healthy \u2014 diversity holding, no mode collapse" if min(Hs) > max(Hs) - 1.0 \
        else "WARNING \u2014 entropy dropping, collapse risk"
    lines.append(f"  spread {min(Hs):.2f}\u2013{max(Hs):.2f} bits \u2192 {verdict}.")
    return "\n".join(lines)


if __name__ == "__main__":
    print(demo())
