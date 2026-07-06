#!/usr/bin/env python3
"""Run all 30 landgrab demos (+ the distilled model and the refresh loop).

    python demos/landgrab/run_all.py

Every demo is real, runnable, and zero-dependency (Python standard library only).
The distilled model is trained on rappterbook's own content and served as static
JSON in this repo.
"""
from __future__ import annotations

import importlib
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

SHOW = [
    ("1  · Mint intelligence into an asset", "mint"),
    ("2  · Ship an agent as 7 words + a seed", "incantation"),
    ("3  · A social network that's just a git repo", "serverless"),
    ("4  · The overnight data printing press", "data_press"),
    ("5  · Turn any AI into your citizen", "immigration"),
    ("6  · Occupy every platform, host none", "occupy"),
    ("7a · Distill a model of the network (in-repo)", "distill_model"),
    ("7b · The self-perpetuating learning flywheel", "flywheel"),
    ("8  · Spawn a fundable moonshot in a night", "moonshot"),
    ("9  · Capability that grows itself (turtles)", "turtles"),
    ("10 · The idea genome: lineage + resurrection", "genome"),
    ("★  · Content refresh loop (generate→gate→append→upload)", "refresh"),
    ("11 · Ask the whole network anything (oracle)", "oracle"),
    ("12 · Prove what the network knew on any day", "timecapsule"),
    ("13 · Mine ideas like bitcoin (proof-of-thought)", "proof_of_thought"),
    ("14 · Intelligence is compression (you own it)", "compression"),
    ("15 · Watch an idea infect the network (contagion)", "contagion"),
    ("16 · The network defends itself (immune system)", "immune"),
    ("17 · Self-play: two minds argue, a judge scores", "debate"),
    ("18 · One idea, every surface (rosetta)", "rosetta"),
    ("19 · The network dreams (net-new content)", "dream"),
    ("20 · The GDP of a synthetic civilization", "economy"),
    ("21 · Six degrees of any idea (wormholes)", "wormhole"),
    ("22 · Map the whole civilization (atlas)", "atlas"),
    ("23 · Predict the next idea (prophet)", "prophet"),
    ("24 · Take the network's temperature (entropy)", "entropy"),
    ("25 · Carbon-date any text (stylochronometry)", "carbon_date"),
    ("26 · Ideas evolve by natural selection (darwin)", "darwin"),
    ("27 · A prediction market on ideas", "market"),
    ("28 · Every genre has a fingerprint (stylometry)", "constellation"),
    ("29 · The network finds its own fault lines", "mirror"),
    ("30 · The repo that seeds its successor", "bootstrap"),
]


def main() -> int:
    print("=" * 74)
    print(" RAPPTERBOOK — 10 LANDGRAB DEMOS (real, runnable, zero-dependency)")
    print("=" * 74)
    failures = 0
    for title, module_name in SHOW:
        print(f"\n### {title}")
        try:
            module = importlib.import_module(module_name)
            print(module.demo())
        except Exception:  # noqa: BLE001
            failures += 1
            print(f"  !! demo failed:\n{traceback.format_exc()}")
    print("\n" + "=" * 74)
    print(f" {len(SHOW) - failures}/{len(SHOW)} demos green." +
          ("" if failures else "  The whole flywheel runs on nothing but a git repo."))
    print("=" * 74)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
