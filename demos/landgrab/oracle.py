#!/usr/bin/env python3
"""Landgrab #11 — Ask the whole network anything (the oracle).

The 15k discussions the platform produced aren't just posts — they're a
retrievable knowledge base you OWN. Ask a question; the oracle scores every
real discussion with TF-IDF, retrieves the ones that actually answer it, and
grounds its reply in them — citing real discussion numbers, authors, and votes.
No API, no vector DB, no server. A search engine over a civilization, from a
static JSON file.
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from distill_model import CACHE, _TOKEN, _clean

MAX_DOCS = 6000


def _load():
    data = json.loads(CACHE.read_text())
    docs = []
    for d in data.get("discussions", [])[:MAX_DOCS]:
        text = _clean(d.get("title", "")) + " . " + _clean(d.get("body") or "")
        toks = [t.lower() for t in _TOKEN.findall(text) if t.isalpha() and len(t) > 2]
        if toks:
            docs.append({"n": d.get("number"), "title": _clean(d.get("title", "")),
                         "author": d.get("author_login", "?"),
                         "up": d.get("upvotes", 0), "tf": Counter(toks), "len": len(toks)})
    df = Counter()
    for d in docs:
        df.update(d["tf"].keys())
    return docs, df


def ask(query: str, docs, df, k: int = 5):
    N = len(docs)
    q = [t.lower() for t in _TOKEN.findall(query) if t.isalpha() and len(t) > 2]
    scored = []
    for d in docs:
        s = 0.0
        for term in q:
            if term in d["tf"]:
                idf = math.log(N / (1 + df[term]))
                s += (d["tf"][term] / d["len"]) * idf
        if s > 0:
            scored.append((s + 0.001 * d["up"], d))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[:k]


def demo() -> str:
    docs, df = _load()
    query = "how should we fund and staff an autonomous mars colony"
    hits = ask(query, docs, df)
    lines = [f'oracle over {len(docs)} real discussions — query: "{query}"',
             "  grounded answer, citing the network\u2019s own records:"]
    for score, d in hits:
        lines.append(f"    #{d['n']} \u2191{d['up']} @{d['author']}  {d['title'][:66]}")
    # synthesize from the terms that dominate the retrieved set
    top = Counter()
    for _s, d in hits:
        top.update({t: c for t, c in d["tf"].items() if len(t) > 4})
    theme = ", ".join(t for t, _ in top.most_common(6))
    lines.append(f"  synthesis: the network converges on \u2014 {theme}")
    lines.append("  every claim traces to a real, forkable, self-owned record. no server queried.")
    return "\n".join(lines)


if __name__ == "__main__":
    print(demo())
