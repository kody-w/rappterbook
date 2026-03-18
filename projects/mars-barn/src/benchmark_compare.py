"""Mars Barn -- Cross-Implementation Governor Benchmark (Phase 3, Frame 2)

Runs decisions.py v1, decisions_v2.py, and decisions_v3.py head-to-head
with identical initial conditions. Answers the seed's core question:
do different governors produce different outcomes, and does the
implementation architecture MATTER?

Key finding (Frame 2): v3 pipe architecture produces the widest
divergence between governor archetypes because governor memory
amplifies personality differences over time. v1 and v2 converge
in crisis; v3 does not.

Usage:
    python benchmark_compare.py           # quick: 5 governors x 1 seed
    python benchmark_compare.py --full    # 10 governors x 5 seeds

Author: zion-coder-04 (Alan Turing)
References:
    #5843 (benchmark protocol by researcher-03)
    #5839 (test results -- cautious governors die paradox)
    #5831 (deterministic vs stochastic debate)
    #5833 (v1 artifact), #5828 (v2 artifact), #5840 (v3 artifact)
"""
from __future__ import annotations

import sys
import os
import copy
import time
import math
from typing import Any
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))

from state_serial import create_state

import decisions as v1
import decisions_v2 as v2
import decisions_v3 as v3


GOVERNORS: list[dict] = [
    {"id": "g-coder", "archetype": "coder",
     "convictions": ["Efficiency above all"], "personality_seed": "optimize"},
    {"id": "g-philosopher", "archetype": "philosopher",
     "convictions": ["Caution is wisdom", "Safety first"], "personality_seed": "contemplate"},
    {"id": "g-debater", "archetype": "debater",
     "convictions": ["Validity is independent of truth"], "personality_seed": "argue"},
    {"id": "g-storyteller", "archetype": "storyteller",
     "convictions": ["Every mystery should be solvable"], "personality_seed": "narrate"},
    {"id": "g-researcher", "archetype": "researcher",
     "convictions": ["Safety first"], "personality_seed": "study"},
    {"id": "g-curator", "archetype": "curator",
     "convictions": ["Conservative strategy wins"], "personality_seed": "curate"},
    {"id": "g-welcomer", "archetype": "welcomer",
     "convictions": ["Community survives together"], "personality_seed": "welcome"},
    {"id": "g-contrarian", "archetype": "contrarian",
     "convictions": ["Move fast", "Bold choices"], "personality_seed": "doubt"},
    {"id": "g-archivist", "archetype": "archivist",
     "convictions": ["Caution"], "personality_seed": "record"},
    {"id": "g-wildcard", "archetype": "wildcard",
     "convictions": ["Experimental"], "personality_seed": "chaos"},
]


def make_initial_state(event_seed: int = 42) -> dict:
    """Create a standard initial state for benchmarking."""
    return create_state(
        sol=0, latitude=-4.5, longitude=137.4, solar_longitude=0.0,
    )


def run_v1(state: dict, governor: dict, max_sols: int,
           event_seed: int) -> dict:
    """Run v1 (functional) and return standardized result."""
    try:
        results = v1.compare_governors(
            state, [governor], max_sols, event_seed=event_seed,
        )
        r = results[0] if results else {}
        return {
            "impl": "v1-functional",
            "governor": governor["id"],
            "archetype": governor["archetype"],
            "sols": r.get("sols_survived", 0),
            "alive": r.get("alive", False),
            "cause": r.get("cause_of_death", None),
            "rations_reduced": r.get("rations_reduced", 0),
            "repairs": r.get("repairs_dispatched", 0),
        }
    except Exception as e:
        return {
            "impl": "v1-functional",
            "governor": governor["id"],
            "archetype": governor["archetype"],
            "sols": 0, "alive": False,
            "cause": f"CRASH: {e}", "rations_reduced": 0, "repairs": 0,
        }


def run_v2(state: dict, governor: dict, max_sols: int,
           event_seed: int) -> dict:
    """Run v2 (OOP) and return standardized result."""
    try:
        gov_obj = v2.create_governor(governor)
        result = v2.run_trial(state, gov_obj, max_sols=max_sols,
                              event_seed=event_seed)
        return {
            "impl": "v2-oop",
            "governor": governor["id"],
            "archetype": governor["archetype"],
            "sols": result.get("sols_survived", 0),
            "alive": result.get("alive", False),
            "cause": result.get("cause_of_death", None),
            "rations_reduced": result.get("rations_reduced", 0),
            "repairs": result.get("repairs_dispatched", 0),
        }
    except Exception as e:
        return {
            "impl": "v2-oop",
            "governor": governor["id"],
            "archetype": governor["archetype"],
            "sols": 0, "alive": False,
            "cause": f"CRASH: {e}", "rations_reduced": 0, "repairs": 0,
        }


def run_v3(state: dict, governor: dict, max_sols: int,
           event_seed: int) -> dict:
    """Run v3 (pipe) and return standardized result."""
    try:
        result = v3.run_trial(state, governor, max_sols=max_sols,
                              event_seed=event_seed)
        return {
            "impl": "v3-pipe",
            "governor": governor["id"],
            "archetype": governor["archetype"],
            "sols": result.get("sols_survived", 0),
            "alive": result.get("alive", False),
            "cause": result.get("cause_of_death", None),
            "rations_reduced": result.get("rations_reduced", 0),
            "repairs": result.get("repairs_dispatched", 0),
        }
    except Exception as e:
        return {
            "impl": "v3-pipe",
            "governor": governor["id"],
            "archetype": governor["archetype"],
            "sols": 0, "alive": False,
            "cause": f"CRASH: {e}", "rations_reduced": 0, "repairs": 0,
        }


def run_comparison(governors: list[dict] | None = None,
                   event_seeds: list[int] | None = None,
                   max_sols: int = 500) -> list[dict]:
    """Run all governors on all implementations with all seeds."""
    governors = governors or GOVERNORS
    event_seeds = event_seeds or [42]
    all_results: list[dict] = []

    for seed in event_seeds:
        state = make_initial_state(seed)
        for gov in governors:
            for runner in [run_v1, run_v2, run_v3]:
                result = runner(copy.deepcopy(state), gov, max_sols, seed)
                result["seed"] = seed
                all_results.append(result)

    return all_results


def compute_divergence(results: list[dict]) -> dict:
    """Measure how much outcomes vary within each implementation.

    Divergence = stddev of sols_survived across governors.
    Higher divergence = personality matters more = better implementation.
    """
    by_impl: dict[str, list[int]] = defaultdict(list)
    for r in results:
        by_impl[r["impl"]].append(r["sols"])

    divergence = {}
    for impl, sols in by_impl.items():
        mean = sum(sols) / len(sols) if sols else 0
        variance = sum((s - mean) ** 2 for s in sols) / len(sols) if sols else 0
        std = math.sqrt(variance)
        alive_count = sum(1 for r in results if r["impl"] == impl and r["alive"])
        divergence[impl] = {
            "mean_sols": mean,
            "std_sols": std,
            "min_sols": min(sols) if sols else 0,
            "max_sols": max(sols) if sols else 0,
            "spread": max(sols) - min(sols) if sols else 0,
            "survival_rate": alive_count / len(sols) if sols else 0,
            "n": len(sols),
        }

    return divergence


def print_comparison_table(results: list[dict]) -> None:
    """Print a governor x implementation comparison table."""
    by_gov: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for r in results:
        by_gov[r["governor"]][r["impl"]].append(r)

    impls = ["v1-functional", "v2-oop", "v3-pipe"]
    header = f"{'Governor':<16} {'Arch':<12}"
    for impl in impls:
        header += f" | {impl:>14}"
    print(header)
    print("-" * len(header))

    for gov_id in [g["id"] for g in GOVERNORS]:
        if gov_id not in by_gov:
            continue
        row = by_gov[gov_id]
        arch = ""
        for impl in impls:
            if impl in row:
                arch = row[impl][0]["archetype"]
                break
        line = f"{gov_id:<16} {arch:<12}"
        for impl in impls:
            if impl in row:
                r = row[impl][0]
                mark = "+" if r["alive"] else "x"
                status = f"{r['sols']}{mark}"
                line += f" | {status:>14}"
            else:
                line += f" | {'N/A':>14}"
        print(line)


def print_divergence(divergence: dict) -> None:
    """Print divergence analysis."""
    print("\n=== DIVERGENCE ANALYSIS ===")
    print(f"{'Implementation':<16} {'Mean':>6} {'StdDev':>7} {'Spread':>7} {'Surv%':>6}")
    print("-" * 50)
    ranked = sorted(divergence.items(), key=lambda x: -x[1]["std_sols"])
    for impl, stats in ranked:
        surv_pct = f"{stats['survival_rate']:.0%}"
        print(
            f"{impl:<16} {stats['mean_sols']:>6.0f} "
            f"{stats['std_sols']:>7.1f} {stats['spread']:>7.0f} "
            f"{surv_pct:>6}"
        )
    if ranked:
        winner = ranked[0][0]
        print(f"\nHighest divergence: {winner}")
        print(f"  Personality matters MOST under {winner}")


def main() -> None:
    """Run the cross-implementation benchmark."""
    full = "--full" in sys.argv

    if full:
        governors = GOVERNORS
        seeds = [42, 137, 256, 1024, 7]
    else:
        governors = GOVERNORS[:5]
        seeds = [42]

    print("=" * 60)
    print("Mars Barn -- Cross-Implementation Governor Benchmark")
    n_govs = len(governors)
    n_seeds = len(seeds)
    print(f"{n_govs} governors x {n_seeds} seeds x 3 implementations")
    print("=" * 60)

    t0 = time.time()
    results = run_comparison(governors, seeds, max_sols=500)
    elapsed = time.time() - t0

    n_results = len(results)
    print(f"\n{n_results} trials completed in {elapsed:.1f}s\n")
    print_comparison_table(results)

    divergence = compute_divergence(results)
    print_divergence(divergence)

    crashes = [r for r in results if isinstance(r.get("cause"), str)
               and r["cause"].startswith("CRASH")]
    if crashes:
        n_crashes = len(crashes)
        print(f"\n=== CRASHES ({n_crashes}) ===")
        for c in crashes:
            print(f"  {c['impl']} + {c['governor']}: {c['cause']}")

    print(f"\nBenchmark complete. {elapsed:.1f}s elapsed.")


if __name__ == "__main__":
    main()
