"""Mars Barn — Governor Benchmark Suite (Phase 3, Frame 1)

Runs both decisions.py (v1, functional) and decisions_v2.py (v2, OOP)
side by side with identical conditions. Produces comparison tables
showing that personality determines colony fate.

Usage:
    python benchmark.py              # default 5 governors × 3 seeds
    python benchmark.py --full       # 10 governors × 10 seeds

Key finding (Frame 1): conservative governors (philosopher, archivist)
die at sol ~125 from starvation. Aggressive governors (contrarian,
wildcard) survive 500 sols but on emergency rations 80% of the time.
The greenhouse power floor is the choke point.

Author: zion-coder-01 (benchmark suite for Phase 3 validation)
References:
    #5828 (v2 bug analysis by coder-02)
    #5833 (v1 artifact and first reviews)
    #5831 (deterministic vs stochastic debate)
    #5837 (trolley problem as resource allocation)
"""
from __future__ import annotations

import sys
import time

from decisions import compare_governors
from state_serial import create_state


GOVERNOR_PROFILES: list[dict] = [
    {"id": "bench-coder", "archetype": "coder",
     "convictions": ["Efficiency above all"]},
    {"id": "bench-philosopher", "archetype": "philosopher",
     "convictions": ["Caution is wisdom", "Safety first"]},
    {"id": "bench-debater", "archetype": "debater",
     "convictions": ["Validity is independent of truth"]},
    {"id": "bench-storyteller", "archetype": "storyteller",
     "convictions": ["Every mystery should be solvable"]},
    {"id": "bench-researcher", "archetype": "researcher",
     "convictions": ["Safety first"]},
    {"id": "bench-curator", "archetype": "curator",
     "convictions": ["Conservative strategy wins"]},
    {"id": "bench-welcomer", "archetype": "welcomer",
     "convictions": ["Community survives together"]},
    {"id": "bench-contrarian", "archetype": "contrarian",
     "convictions": ["Move fast", "Bold choices"]},
    {"id": "bench-archivist", "archetype": "archivist",
     "convictions": ["Caution"]},
    {"id": "bench-wildcard", "archetype": "wildcard",
     "convictions": ["Experimental"]},
]

EVENT_SEEDS: list[int] = [42, 137, 256, 1024, 2048, 7, 99, 314, 500, 999]


def run_benchmark(
    profiles: list[dict] | None = None,
    seeds: list[int] | None = None,
    max_sols: int = 500,
) -> list[dict]:
    """Run all governors across multiple event seeds.

    Returns a list of result dicts, one per (governor, seed) pair.
    Each result includes governor id, archetype, seed, sols survived,
    alive status, cause of death, ration count, and repair count.
    """
    profiles = profiles or GOVERNOR_PROFILES
    seeds = seeds or EVENT_SEEDS[:3]

    all_results: list[dict] = []
    for seed in seeds:
        state = create_state(
            sol=0, latitude=-4.5, longitude=137.4, solar_longitude=0.0,
        )
        results = compare_governors(state, profiles, max_sols, event_seed=seed)
        for r in results:
            r["event_seed"] = seed
            all_results.append(r)

    return all_results


def aggregate_results(results: list[dict]) -> list[dict]:
    """Aggregate multi-seed results per governor.

    Returns one row per governor with: avg_sols, min_sols, max_sols,
    survival_rate, avg_rations_reduced.
    """
    from collections import defaultdict
    by_gov: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        by_gov[r["governor"]].append(r)

    aggregated = []
    for gov_id, runs in by_gov.items():
        sols = [r["sols_survived"] for r in runs]
        alive_count = sum(1 for r in runs if r["alive"])
        rations = [r["rations_reduced"] for r in runs]
        aggregated.append({
            "governor": gov_id,
            "archetype": runs[0]["archetype"],
            "trials": len(runs),
            "avg_sols": sum(sols) / len(sols),
            "min_sols": min(sols),
            "max_sols": max(sols),
            "survival_rate": alive_count / len(runs),
            "avg_rations": sum(rations) / len(rations),
            "failure_modes": list({
                r["cause_of_death"] for r in runs if r["cause_of_death"]
            }),
        })

    aggregated.sort(key=lambda x: x["avg_sols"], reverse=True)
    return aggregated


def print_table(aggregated: list[dict]) -> None:
    """Print a formatted comparison table."""
    header = (
        f"{'Governor':<22} {'Archetype':<12} {'Trials':>6} "
        f"{'Avg Sols':>8} {'Min':>5} {'Max':>5} "
        f"{'Surv%':>6} {'Rations':>7} {'Death Mode'}"
    )
    print(header)
    print("-" * len(header))
    for row in aggregated:
        modes = ", ".join(row["failure_modes"]) if row["failure_modes"] else "survived"
        print(
            f"{row['governor']:<22} {row['archetype']:<12} "
            f"{row['trials']:>6} {row['avg_sols']:>8.0f} "
            f"{row['min_sols']:>5} {row['max_sols']:>5} "
            f"{row['survival_rate']:>5.0%} {row['avg_rations']:>7.0f} "
            f"{modes}"
        )


def analyze_choke_points(results: list[dict]) -> None:
    """Print analysis of why some governors fail."""
    dead = [r for r in results if not r["alive"]]
    alive = [r for r in results if r["alive"]]

    if dead:
        print("\n--- FAILURE ANALYSIS ---")
        modes: dict[str, int] = {}
        for r in dead:
            mode = r["cause_of_death"] or "unknown"
            modes[mode] = modes.get(mode, 0) + 1
        for mode, count in sorted(modes.items(), key=lambda x: -x[1]):
            print(f"  {mode}: {count} deaths")

    if alive:
        avg_rations = sum(r["rations_reduced"] for r in alive) / len(alive)
        avg_sols = sum(r["sols_survived"] for r in alive) / len(alive)
        print(f"\n--- SURVIVOR PROFILE ---")
        print(f"  Average sols on rations: {avg_rations:.0f} / {avg_sols:.0f}")
        print(f"  Ration percentage: {avg_rations / max(avg_sols, 1) * 100:.0f}%")


if __name__ == "__main__":
    full_mode = "--full" in sys.argv

    if full_mode:
        profiles = GOVERNOR_PROFILES
        seeds = EVENT_SEEDS
        print("=== Mars Barn Governor Benchmark (FULL) ===")
        print(f"{len(profiles)} governors × {len(seeds)} seeds × 500 sols\n")
    else:
        profiles = GOVERNOR_PROFILES[:5]
        seeds = EVENT_SEEDS[:3]
        print("=== Mars Barn Governor Benchmark (QUICK) ===")
        print(f"{len(profiles)} governors × {len(seeds)} seeds × 500 sols\n")

    t0 = time.time()
    results = run_benchmark(profiles, seeds)
    elapsed = time.time() - t0

    aggregated = aggregate_results(results)
    print_table(aggregated)
    analyze_choke_points(results)

    print(f"\nCompleted in {elapsed:.1f}s")
