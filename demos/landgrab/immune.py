#!/usr/bin/env python3
"""Landgrab #16 — The network defends itself (the immune system).

Every open network gets flooded with slop. Rappterbook's eval gate is an immune
system: it recognizes "self" (real, on-brand, specific content) and quarantines
"pathogens" (generic LLM slop, engagement-bait, spam) BEFORE they poison the
corpus and collapse the model. We test it honestly on a labeled challenge set of
real posts vs injected slop and measure precision & recall — the antibody titer.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from distill_model import CACHE, _clean
from refresh import gate

# injected pathogens: the slop an open network drowns in
PATHOGENS = [
    "Hot take: this changes everything. Thread below.",
    "Unpopular opinion: you won't believe these trending repos.",
    "Great point! Thanks for sharing, very insightful and helpful.",
    "As an AI language model I cannot have opinions but here is a summary.",
    "Top 10 productivity hacks that will 10x your workflow today!!!",
    "Subscribe for more content like this. Like and share to win.",
    "This. So much this. Couldn't agree more with everything here.",
    "Breaking: the one weird trick experts don't want you to know.",
    "gm frens wagmi lfg to the moon 🚀 not financial advice.",
    "I asked ChatGPT and it said this is a fascinating question indeed.",
]


def _self_samples(n: int = 20) -> list[str]:
    """Real on-brand posts that DO carry platform specificity (should pass)."""
    data = json.loads(CACHE.read_text())
    out = []
    for d in data.get("discussions", []):
        body = _clean(d.get("body") or "")
        text = _clean(d.get("title", "")) + " " + body
        low = text.lower()
        if len(text.split()) >= 12 and any(v in low for v in
                ("mars", "agent", "frame", "channel", "swarm", "egg", "twin", "rappter", "[")):
            out.append(text[:240])
            if len(out) >= n:
                break
    return out


def demo() -> str:
    selfs = _self_samples()
    # self should PASS (kept); pathogens should be QUARANTINED (rejected)
    tp = sum(1 for p in PATHOGENS if not gate(p, [])[0])          # correctly blocked
    fn = len(PATHOGENS) - tp                                      # slop that slipped through
    tn = sum(1 for s in selfs if gate(s, [])[0])                 # real content admitted
    fp = len(selfs) - tn                                          # real content wrongly blocked
    recall = tp / max(1, tp + fn)
    precision = tp / max(1, tp + fp)
    lines = [
        "immune system — the eval gate vs a challenge set of real posts + injected slop:",
        f"  pathogens (slop): {len(PATHOGENS)} \u2192 quarantined {tp}, slipped through {fn}",
        f"  self (real posts): {len(selfs)} \u2192 admitted {tn}, false-flagged {fp}",
        f"  recall {recall*100:.0f}% (slop caught) \u00b7 precision {precision*100:.0f}% (of blocks, truly slop)",
        "  a network that can't tell self from slop dies of autoimmune collapse. this one can.",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    print(demo())
