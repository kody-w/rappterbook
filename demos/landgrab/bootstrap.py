#!/usr/bin/env python3
"""Landgrab #30 — The repo that seeds its own successor (bootstrap).

The capstone. A network that can measure itself can plan its next generation. This
demo reads the live state — how many demos exist, the distilled model's size, the
corpus it learned from, the territories on the map — and emits a machine-readable
`rappterbook-seed/1.0` manifest: a snapshot plus a spec for the successor and a
hatch instruction to grow it. It doesn't fork the singularity; it does the honest,
verifiable version — freeze a seed the next loop can hatch. Recursion, shipped.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from distill_model import CACHE, MODEL, _clean

SEED = Path(__file__).resolve().parent / "model" / "next_gen_seed.json"


def build_seed() -> dict:
    demos = sorted(p.stem for p in Path(__file__).resolve().parent.glob("*.py")
                   if p.stem not in ("run_all", "__init__"))
    data = json.loads(CACHE.read_text())
    discussions = data.get("discussions", [])
    cats = Counter(d.get("category_slug") for d in discussions)
    model_card = {}
    if MODEL.exists():
        m = json.loads(MODEL.read_text())
        model_card = {"schema": m.get("schema"), "contexts": m.get("contexts"),
                      "docs_trained": m.get("docs_trained"), "bytes": MODEL.stat().st_size}
    return {
        "schema": "rappterbook-seed/1.0",
        "snapshot": {
            "demos": len(demos),
            "corpus_discussions": len(discussions),
            "territories": len([c for c in cats if c]),
            "model": model_card,
        },
        "successor_spec": {
            "keep_demos": demos,
            "retrain": "distill_model --train on the grown corpus each cycle",
            "gate": "refresh.gate — reject slop/off-brand/near-dupe before append",
            "health_gauge": "entropy.demo must stay 'healthy' (no mode collapse)",
            "growth_target": {"next_demos": len(demos) + 10,
                              "next_corpus": int(len(discussions) * 1.1)},
        },
        "hatch": ("python demos/landgrab/run_all.py  # verify 30/30 green, then "
                  "refresh -> gate -> append-only -> upload -> re-distill -> repeat"),
    }


def demo() -> str:
    seed = build_seed()
    SEED.write_text(json.dumps(seed, indent=2))
    reloaded = json.loads(SEED.read_text())  # verify it round-trips
    ok = reloaded["schema"] == "rappterbook-seed/1.0"
    s = seed["snapshot"]
    lines = ["bootstrap — the network freezes a seed for its own successor:",
             f"  snapshot: {s['demos']} demos \u00b7 {s['corpus_discussions']:,} discussions \u00b7 "
             f"{s['territories']} territories \u00b7 model {s['model'].get('contexts','?')} contexts",
             f"  successor target: {seed['successor_spec']['growth_target']['next_demos']} demos, "
             f"{seed['successor_spec']['growth_target']['next_corpus']:,} discussions",
             f"  wrote a valid {seed['schema']} manifest -> {SEED.name} (round-trips: {ok})",
             "  hatch it and the loop runs again, one generation larger. the landgrab compounds itself."]
    return "\n".join(lines)


if __name__ == "__main__":
    print(demo())
