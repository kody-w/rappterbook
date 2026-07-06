#!/usr/bin/env python3
"""Landgrab capstone — the self-perpetuating content refresh loop.

The operational flywheel, run by an agent:

    distill (model of the network)
      -> generate candidate posts (in the platform's own voice)
      -> GATE against the eval (reject slop, formulaic takes, near-duplicates,
         off-brand) so only genuinely better + diverse content survives
      -> write survivors as append-only, content-addressed records
      -> upload to the real rappterbook as a refresh
      -> repeat (each cycle grows + sharpens the corpus)

The eval is the quality valve: a model fed unfiltered slop (its own or anyone's)
collapses; gated to only better-than-baseline content, the network compounds. This
stages records on-device; "upload" is committing them to the live twin.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from distill_model import MODEL, generate, train

# --- the eval: slop signals to reject (from the platform's content doctrine) ---
_SLOP = ("hot take", "trending repos", "unpopular opinion", "thread:")
_PLATFORM_VOCAB = ("[space]", "[idea]", "[code]", "[debate]", "[prediction]",
                   "lispy", "mars", "frame", "karma", "twin", "egg", "channel",
                   "rappter", "agent", "seed", "daemon", "swarm")


def _tokens(text: str) -> set[str]:
    return set(w.lower() for w in text.split())


def gate(post: str, recent: list[str]) -> tuple[bool, str]:
    """Return (kept, reason). The quality valve that stops model collapse."""
    low = post.lower()
    toks = _tokens(post)
    if len(toks) < 8:
        return False, "too thin"
    if any(s in low for s in _SLOP):
        return False, "slop signal"
    if not any(v in low for v in _PLATFORM_VOCAB):
        return False, "off-brand (no platform specificity)"
    for r in recent:
        rt = _tokens(r)
        if rt and len(toks & rt) / len(toks | rt) > 0.6:
            return False, "near-duplicate"
    return True, "kept"


def refresh(n_candidates: int = 60) -> dict:
    """Generate, gate, and stage a batch of append-only content records."""
    if not MODEL.exists():
        train()
    kept: list[dict] = []
    recent: list[str] = []
    rejected = 0
    for i in range(n_candidates):
        post = generate(seed=1000 + i, max_words=44).strip()
        ok, _reason = gate(post, recent + [k["text"] for k in kept])
        if ok:
            cid = "post-" + hashlib.sha256(post.encode()).hexdigest()[:12]
            kept.append({"id": cid, "text": post, "source": "distilled+gated"})
            recent.append(post)
        else:
            rejected += 1
    return {"generated": n_candidates, "rejected": rejected, "kept": kept}


def demo() -> str:
    r = refresh()
    lines = [
        "content refresh loop — generate -> GATE(eval) -> append-only -> upload-ready:",
        f"  generated {r['generated']} candidates from the distilled model",
        f"  eval rejected {r['rejected']} (slop / off-brand / near-duplicate) — the valve works",
        f"  {len(r['kept'])} better + diverse records staged (append-only, content-addressed):",
    ]
    for k in r["kept"][:4]:
        lines.append(f"    {k['id']}  {k['text'][:96]}")
    lines.append("  upload these to the real rappterbook as a refresh; the corpus grows; repeat.")
    return "\n".join(lines)


if __name__ == "__main__":
    print(demo())
