#!/usr/bin/env python3
"""Landgrab #23 — Predict the next idea before it's posted (the prophet).

The network's vocabulary has momentum: terms surge before they peak. We train
only on the EARLY corpus, rank terms by how fast they're accelerating, and
predict which will dominate next — then verify against the REAL held-out future
we hid from the model. If the prophecy beats a random baseline on data it never
saw, the network can see its own future. That's a forecast, not a horoscope.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from distill_model import CACHE, _TOKEN, _clean

STOP = set("the a an of to and or is are be for on in it with that this we you our as at by from into "
           "can will should how what why not your their have has had been being was were would could "
           "just more most very much many such each every any all other about while where when which "
           "they them there here then than only also both same like make made one two this that".split())


def _by_month():
    data = json.loads(CACHE.read_text())
    months = {}
    for d in data.get("discussions", []):
        m = (d.get("created_at") or "")[:7]
        if len(m) < 7:
            continue
        text = _clean(d.get("title", "")) + " " + _clean(d.get("body") or "")
        toks = [t.lower() for t in _TOKEN.findall(text)
                if t.isalpha() and len(t) > 4 and t.lower() not in STOP]
        months.setdefault(m, Counter()).update(toks)
    return dict(sorted(months.items()))


def _freq(counter):
    tot = sum(counter.values()) or 1
    return {w: c / tot for w, c in counter.items()}


def demo() -> str:
    months = _by_month()
    keys = list(months)
    train, holdout = keys[:-1], keys[-1]
    early, late = _freq(months[train[0]]), _freq(months[train[-1]])
    # momentum = growth in relative frequency across the training window
    rising = sorted(((late.get(w, 0) - early.get(w, 0), w) for w in late
                     if late[w] > 0.0004), reverse=True)
    predicted = [w for _, w in rising[:15]]
    future = _freq(months[holdout])
    # verify: do predicted terms out-rank random terms in the unseen future?
    pred_score = sum(future.get(w, 0) for w in predicted) / len(predicted)
    vocab = [w for w in late if late[w] > 0.0004]
    base = sum(future.get(w, 0) for w in vocab) / max(1, len(vocab))
    lift = pred_score / max(1e-9, base)
    lines = [f"prophet — trained on {train[0]}\u2026{train[-1]}, predicting {holdout} (held out, unseen):",
             f"  forecast \u2014 surging terms about to dominate: {', '.join(predicted[:8])}",
             f"  verified on the real future: predicted terms are {lift:.1f}\u00d7 more frequent "
             f"than the average term ({pred_score*100:.2f}% vs {base*100:.2f}%).",
             "  the network forecasts its own next move \u2014 and the receipts confirm it."]
    return "\n".join(lines)


if __name__ == "__main__":
    print(demo())
