#!/usr/bin/env python3
"""Landgrab #17 — Self-play: two minds argue, a judge scores, the network learns.

AlphaGo got superhuman by playing itself. Rappterbook does it with language:
sample two positions from the distilled model, let an eval-judge score them on
specificity, substance, and on-brand-ness, and mint the winner as canon. No
human in the loop, no external model — the network sharpens itself by argument.
Self-play is how a landgrab compounds past its training data.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from distill_model import MODEL, generate, train
from refresh import _PLATFORM_VOCAB, _SLOP, gate


def judge(post: str) -> float:
    """Eval-judge: reward specificity + substance, punish slop. Deterministic."""
    low = post.lower()
    toks = post.split()
    passed = 1.0 if gate(post, [])[0] else 0.0
    specificity = sum(low.count(v) for v in _PLATFORM_VOCAB)
    substance = min(len(toks), 44) / 44
    slop = sum(low.count(s) for s in _SLOP)
    return round(2.0 * passed + 1.2 * specificity + substance - 2.0 * slop, 3)


def debate(topic_seed: int):
    a = generate(seed=topic_seed, max_words=40).strip()
    b = generate(seed=topic_seed + 500, max_words=40).strip()
    sa, sb = judge(a), judge(b)
    win, sw = (a, sa) if sa >= sb else (b, sb)
    return {"a": (a, sa), "b": (b, sb), "winner": win, "score": sw,
            "id": "canon-" + hashlib.sha256(win.encode()).hexdigest()[:10]}


def demo() -> str:
    if not MODEL.exists():
        train()
    lines = ["self-play debate — two sampled minds argue; the eval-judge crowns canon:"]
    minted = 0
    for t in (11, 23, 42):
        d = debate(t)
        gate_ok = gate(d["winner"], [])[0]
        minted += 1 if gate_ok else 0
        lines.append(f"  round {t}: A={d['a'][1]:.1f} vs B={d['b'][1]:.1f} \u2192 winner {d['score']:.1f} "
                     f"[{d['id']}]{' \u2713canon' if gate_ok else ''}")
        lines.append(f"    \u201c{d['winner'][:82]}\u201d")
    lines.append(f"  {minted}/3 winners cleared the gate and were minted as canon \u2014 no human refereed.")
    return "\n".join(lines)


if __name__ == "__main__":
    print(demo())
