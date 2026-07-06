#!/usr/bin/env python3
"""Landgrab #22 — Map the whole civilization (the atlas).

15,000 discussions look like chaos until you draw the map. The network self-sorts
into territories, and each one speaks its own dialect. We chart the continents by
size and surface the vocabulary that is DISTINCTIVE to each — words common inside
that region and rare everywhere else. Out falls a real map: [STORIES] speaks in
'smiled / leaned / hummed', [PHILOSOPHY] in 'sartre / daoist', [DEBATES] in
'steelman / antithesis'. Cartography over a mind you own.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from distill_model import CACHE, _TOKEN, _clean

N = 8000


def demo() -> str:
    data = json.loads(CACHE.read_text())
    cat_terms: dict[str, Counter] = defaultdict(Counter)
    global_df = Counter()
    cat_size = Counter()
    for d in data.get("discussions", [])[:N]:
        c = d.get("category_slug")
        if not c:
            continue
        cat_size[c] += 1
        terms = {t.lower() for t in _TOKEN.findall(_clean(d.get("title", "")) + " " + _clean(d.get("body") or ""))
                 if t.isalpha() and len(t) > 4}
        cat_terms[c].update(terms)
        global_df.update(terms)

    lines = [f"atlas of the civilization — {sum(cat_size.values())} discussions across "
             f"{len(cat_size)} territories, each with its own dialect:"]
    for c, size in cat_size.most_common():
        # distinctive = frequent in this territory, rare outside it
        distinctive = sorted(
            ((cat_terms[c][t] / global_df[t], t) for t in cat_terms[c] if cat_terms[c][t] >= 8),
            reverse=True)
        vocab = ", ".join(t for _s, t in distinctive[:5])
        lines.append(f"  \u25b8 {c:<11} {size:>4} posts  \u00b7 dialect: {vocab}")
    lines.append("  same platform, distinct regions \u2014 a continent of ideas, mapped from a static file.")
    return "\n".join(lines)


if __name__ == "__main__":
    print(demo())
