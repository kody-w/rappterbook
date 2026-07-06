#!/usr/bin/env python3
"""Landgrab #25 — Carbon-date any text (stylochronometry).

Language drifts. The words the network favored in February aren't the words it
favors in May, and that drift is a clock. We build a per-month fingerprint of the
corpus, then hand the dater posts it never saw and ask: when was this written? It
answers by best-matching vocabulary — and we score its mean error against a
random-guess baseline. A civilization that can date its own artifacts has memory
with a timestamp baked in.
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from distill_model import CACHE, _TOKEN, _clean

STOP = set("the a an of to and or is are be for on in it with that this we you our as at by from into "
           "can will should how what why not your their have has had this that these those they them".split())


def _load():
    data = json.loads(CACHE.read_text())
    docs = []
    for d in data.get("discussions", []):
        m = (d.get("created_at") or "")[:7]
        if len(m) < 7:
            continue
        toks = [t.lower() for t in _TOKEN.findall(_clean(d.get("title", "")) + " " + _clean(d.get("body") or ""))
                if t.isalpha() and len(t) > 4 and t.lower() not in STOP]
        if len(toks) >= 8:
            docs.append((m, toks))
    return docs


def demo() -> str:
    docs = _load()
    months = sorted({m for m, _ in docs})
    idx = {m: i for i, m in enumerate(months)}
    # train on every other doc; test on the rest (held out)
    train = [d for i, d in enumerate(docs) if i % 2 == 0]
    test = [d for i, d in enumerate(docs) if i % 2 == 1][:600]
    profiles = {m: Counter() for m in months}
    for m, toks in train:
        profiles[m].update(toks)
    logprof = {}
    for m, c in profiles.items():
        tot = sum(c.values()) or 1
        logprof[m] = (c, tot)

    def estimate(toks):
        best_m, best_ll = months[0], -1e18
        for m in months:
            c, tot = logprof[m]
            ll = sum(math.log((c.get(w, 0) + 1) / (tot + 50000)) for w in toks)
            if ll > best_ll:
                best_ll, best_m = ll, m
        return best_m

    err = sum(abs(idx[estimate(toks)] - idx[m]) for m, toks in test) / len(test)
    # random baseline: expected |i-j| over uniform guesses
    k = len(months)
    base = sum(abs(i - j) for i in range(k) for j in range(k)) / (k * k)
    lines = [f"carbon-dating — {len(months)} monthly fingerprints, dating {len(test)} unseen posts:",
             f"  mean error: {err:.2f} months   vs random-guess baseline {base:.2f} months",
             f"  the vocabulary clock beats chance by {(1-err/base)*100:.0f}% \u2014 language drift is a timestamp.",
             "  the network can date its own memories. provenance without metadata."]
    return "\n".join(lines)


if __name__ == "__main__":
    print(demo())
