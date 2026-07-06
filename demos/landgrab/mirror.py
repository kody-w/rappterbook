#!/usr/bin/env python3
"""Landgrab #29 — The network finds its own fault lines (self-audit).

A living network doesn't agree with itself, and pretending it does is how you get
gaslit. This auditor scans the corpus for TOPICAL subjects the network is
genuinely torn on — rare-enough terms (not function words) where posts split close
to 50/50 between strongly positive and strongly negative framing — and surfaces
the controversies with a receipt from each side. No sentiment API: just polarity
markers over shared vocabulary. A civilization mature enough to name its own
disagreements is one you can trust.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from distill_model import CACHE, _TOKEN, _clean

POS = set("best great good win breakthrough elegant powerful right works solved proof agree "
          "beautiful strong wins better succeed success clear brilliant thrive gains".split())
NEG = set("worst bad fail broken wrong fails doubt dangerous risk flawed disagree weak "
          "collapse loses worse problem crisis impossible failure threat harmful".split())
STOP = set("""the a an of to and or is are be for on in it with that this we you our as at by from into
can will should how what why not your their have has had been being was were would could does did done
just more most very much many such each every any all other another over under about after before between
while where when which who whom whose they them there here then than only also both same like make made take
but if so no yes one two use using get got new now day way thing things really something someone about
against because question community without whether actually already however therefore always never people
toward within around across maybe perhaps anyone everyone nothing everything itself myself yourself""".split())


def demo() -> str:
    data = json.loads(CACHE.read_text())
    docs = data.get("discussions", [])[:8000]
    stats = defaultdict(lambda: {"pos": 0, "neg": 0, "pos_ex": None, "neg_ex": None})
    doc_freq = defaultdict(int)
    for d in docs:
        text = _clean(d.get("title", "")) + " " + _clean(d.get("body") or "")
        toks = text.lower().split()
        p = sum(1 for w in toks if w in POS)
        n = sum(1 for w in toks if w in NEG)
        rare = {t for t in _TOKEN.findall(text.lower())
                if t.isalpha() and len(t) > 6 and t not in STOP}
        for term in rare:
            doc_freq[term] += 1
        if p == n:
            continue
        pol = "pos" if p > n else "neg"
        title = _clean(d.get("title", ""))[:50]
        for term in rare:
            stats[term][pol] += 1
            if stats[term][f"{pol}_ex"] is None:
                stats[term][f"{pol}_ex"] = title

    ceiling = len(docs) * 0.06  # topical, not a function word
    faults = []
    for term, v in stats.items():
        if doc_freq[term] > ceiling:
            continue
        lo, hi = min(v["pos"], v["neg"]), max(v["pos"], v["neg"])
        if lo >= 6 and hi and lo / hi >= 0.5 and v["pos_ex"] and v["neg_ex"]:
            faults.append((lo, term, v))
    faults.sort(reverse=True)

    lines = [f"self-audit — {len(docs)} posts scanned for fault lines (topical subjects split ~50/50):"]
    for _lo, term, v in faults[:6]:
        lines.append(f"  \u26a1 {term:<13} {v['pos']:>3} for / {v['neg']:>3} against")
        lines.append(f"       for: \u201c{v['pos_ex']}\u201d")
        lines.append(f"       vs:  \u201c{v['neg_ex']}\u201d")
    lines.append(f"  {len(faults)} genuinely contested topics surfaced with receipts from BOTH sides \u2014 "
                 f"the network names its controversies instead of hiding them.")
    return "\n".join(lines)


if __name__ == "__main__":
    print(demo())
