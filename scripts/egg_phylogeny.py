#!/usr/bin/env python3
"""Egg Phylogeny — deterministic egg breeding across N generations.

Mints 4 founding .rappter.egg files with distinct trait genomes, then runs
N generations of mate-selected reproduction with environmental fitness.
Outputs a phylogenetic tree (JSON) showing which traits dominated and which
went extinct, with branch points labeled by generation.

Stdlib only. Deterministic given a seed.

Usage:
    python scripts/egg_phylogeny.py [--generations 50] [--seed 42] [--carry 16]

Outputs:
    state/phylogeny/founders/*.rappter.egg          # 4 founder eggs
    state/phylogeny/run-{ts}/individuals.json       # every individual
    state/phylogeny/run-{ts}/generations.json       # per-gen stats
    state/phylogeny/run-{ts}/tree.json              # phylogenetic tree
    state/phylogeny/run-{ts}/summary.md             # human-readable
    state/phylogeny/latest -> run-{ts}              # symlink to newest
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("STATE_DIR", REPO_ROOT / "state"))
PHYL_DIR = STATE_DIR / "phylogeny"
FOUNDERS_DIR = PHYL_DIR / "founders"

# ---- Trait genome (published, deterministic) -----------------------------

TRAITS: dict[str, list[str]] = {
    "color":       ["crimson", "azure", "verdant", "gold", "obsidian"],
    "pattern":     ["solid", "striped", "spotted", "iridescent", "fractal"],
    "size":        ["tiny", "small", "medium", "large", "giant"],
    "temperament": ["curious", "cautious", "aggressive", "peaceful", "chaotic"],
    "sociability": ["solitary", "pair", "pack", "swarm"],
    "cognition":   ["pattern_matcher", "deep_thinker", "rapid_reactor", "memory_hoarder"],
    "metabolism":  ["efficient", "voracious", "slow_burn", "torpor"],
    "lifespan":    ["mayfly", "normal", "long", "ancient"],
}

# Dominance: when two parents disagree on a trait, the allele with
# the LOWER dominance index wins by default. Ties broken by hash.
DOMINANCE = {trait: {a: i for i, a in enumerate(alleles)} for trait, alleles in TRAITS.items()}

# Founders: 4 maximally distinct genomes covering the trait space.
FOUNDER_GENOMES = [
    {"color": "crimson",  "pattern": "solid",       "size": "small",  "temperament": "aggressive", "sociability": "solitary", "cognition": "rapid_reactor",   "metabolism": "voracious",  "lifespan": "mayfly"},
    {"color": "azure",    "pattern": "iridescent",  "size": "medium", "temperament": "curious",    "sociability": "pair",     "cognition": "deep_thinker",    "metabolism": "efficient",  "lifespan": "long"},
    {"color": "verdant",  "pattern": "spotted",     "size": "large",  "temperament": "peaceful",   "sociability": "pack",     "cognition": "memory_hoarder",  "metabolism": "slow_burn",  "lifespan": "ancient"},
    {"color": "gold",     "pattern": "fractal",     "size": "giant",  "temperament": "chaotic",    "sociability": "swarm",    "cognition": "pattern_matcher", "metabolism": "torpor",     "lifespan": "normal"},
]
FOUNDER_NAMES = ["scarlet-fang", "azure-mind", "verdant-vow", "gold-storm"]


# ---- Egg I/O -------------------------------------------------------------

def make_egg(individual_id: str, generation: int, parents: list[str], genome: dict, lineage_path: list[str]) -> dict:
    """Build a v1-compatible egg envelope around a phylogeny individual."""
    egg = {
        "egg_format_version": "1",
        "species": "rappter",
        "instance": individual_id,
        "scale": "daemon",
        "identity": {
            "id": individual_id,
            "name": individual_id,
            "stage": "egg",
            "generation": generation,
        },
        "genome": dict(genome),
        "lineage": {
            "parents": parents,
            "ancestors": lineage_path,
            "founder_blood": founder_ancestry(lineage_path),
        },
        "_meta": {
            "format": "phylogeny.v1",
            "merge_function": "egg_phylogeny.merge_genomes",
            "spec": "https://github.com/kody-w/rappterbook/blob/main/EGG_SPEC.md",
        },
    }
    return egg


def write_egg(egg: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(egg, indent=2, sort_keys=True))


# ---- Merge function (PUBLISHED, deterministic) --------------------------

def merge_genomes(parent_a_id: str, genome_a: dict, parent_b_id: str, genome_b: dict, generation: int, mutation_rate: float = 0.04) -> dict:
    """Deterministically merge two genomes into an offspring genome.

    For each trait:
      1. If both parents agree, the allele is inherited.
      2. If they disagree, the more dominant allele wins, with stochastic
         (but seed-reproducible) overrides driven by SHA-256 of parent ids.
      3. With probability `mutation_rate`, a mutation replaces the chosen
         allele with a different valid allele for that trait.

    The merge is a pure function of (parent_a_id, parent_b_id, generation).
    Same inputs → same outputs, every time, on any machine.
    """
    offspring = {}
    for trait, alleles in TRAITS.items():
        a_allele = genome_a[trait]
        b_allele = genome_b[trait]
        if a_allele == b_allele:
            chosen = a_allele
        else:
            # Deterministic coin flip from hash
            seed = f"{parent_a_id}|{parent_b_id}|{trait}|gen{generation}"
            h = int(hashlib.sha256(seed.encode()).hexdigest(), 16)
            # Dominance bias: more-dominant allele wins 70% of the time
            a_dom = DOMINANCE[trait][a_allele]
            b_dom = DOMINANCE[trait][b_allele]
            if a_dom < b_dom:
                chosen = a_allele if (h % 100) < 70 else b_allele
            elif b_dom < a_dom:
                chosen = b_allele if (h % 100) < 70 else a_allele
            else:
                chosen = a_allele if (h % 2 == 0) else b_allele

        # Mutation
        mut_seed = f"mutate|{parent_a_id}|{parent_b_id}|{trait}|gen{generation}"
        mut_h = int(hashlib.sha256(mut_seed.encode()).hexdigest(), 16)
        if (mut_h % 10000) < int(mutation_rate * 10000):
            options = [x for x in alleles if x != chosen]
            chosen = options[mut_h % len(options)]

        offspring[trait] = chosen
    return offspring


# ---- Compatibility & fitness --------------------------------------------

def genome_distance(g1: dict, g2: dict) -> int:
    """Hamming distance on traits. 0..len(TRAITS)."""
    return sum(1 for trait in TRAITS if g1[trait] != g2[trait])


def compatibility(g1: dict, g2: dict) -> float:
    """Higher = better mate match. Penalizes identical (inbreeding) AND maximally divergent (incompatible)."""
    d = genome_distance(g1, g2)
    n = len(TRAITS)
    # Sweet spot at ~40% divergence; falls off either side
    if d == 0:
        return 0.0  # cannot mate with self/clone
    ratio = d / n
    # Triangle peak at 0.5, floor of 0.2 so even maximally-distant pairs can mate
    if ratio <= 0.5:
        peak = ratio / 0.5
    else:
        peak = 1.0 - (ratio - 0.5) / 0.5
    return max(0.2, peak)


def environmental_fitness(genome: dict, generation: int) -> float:
    """Environment shifts every 10 generations, applying selection pressure."""
    epoch = generation // 10
    # Seven environmental epochs cycling through different selection regimes
    favored = [
        # epoch 0: cold/scarce
        {"metabolism": ["efficient", "torpor"], "size": ["tiny", "small"], "temperament": ["cautious"]},
        # epoch 1: predator pressure
        {"temperament": ["aggressive", "cautious"], "size": ["tiny", "large"], "sociability": ["pack", "swarm"]},
        # epoch 2: bloom of resources
        {"metabolism": ["voracious"], "size": ["large", "giant"], "lifespan": ["long", "ancient"]},
        # epoch 3: chaos / disease
        {"temperament": ["chaotic", "curious"], "lifespan": ["mayfly"], "metabolism": ["voracious"]},
        # epoch 4: cognitive arms race
        {"cognition": ["deep_thinker", "memory_hoarder"], "lifespan": ["ancient"]},
        # epoch 5: social complexity
        {"sociability": ["pack", "swarm"], "temperament": ["peaceful"], "cognition": ["pattern_matcher"]},
        # epoch 6: stability
        {"metabolism": ["slow_burn"], "lifespan": ["long"], "temperament": ["peaceful", "curious"]},
    ][epoch % 7]
    score = 0.5
    for trait, favored_alleles in favored.items():
        if genome[trait] in favored_alleles:
            score += 0.15
    # Lifespan baseline modifier
    life = {"mayfly": -0.05, "normal": 0, "long": 0.05, "ancient": 0.1}[genome["lifespan"]]
    return max(0.05, score + life)


def founder_ancestry(lineage_path: list[str]) -> dict:
    """Count how many founder genes each individual carries by lineage."""
    counts: dict[str, int] = defaultdict(int)
    for ancestor in lineage_path:
        for f in FOUNDER_NAMES:
            if ancestor == f or ancestor.startswith(f + "-"):
                counts[f] += 1
    return dict(counts)


# ---- Simulation ----------------------------------------------------------

def run_simulation(generations: int, seed: int, carry: int) -> dict:
    """Run the phylogeny simulation. Returns the run state dict."""
    # Seed individuals: 4 founders, each duplicated to fill carrying capacity
    individuals: dict[str, dict] = {}
    population: list[str] = []
    for i, (name, genome) in enumerate(zip(FOUNDER_NAMES, FOUNDER_GENOMES)):
        individuals[name] = {
            "id": name,
            "generation": 0,
            "parents": [],
            "genome": dict(genome),
            "fitness": environmental_fitness(genome, 0),
            "is_founder": True,
            "alive": True,
            "died_at_generation": None,
            "children": [],
        }
        population.append(name)
        # Write founder egg
        egg = make_egg(name, 0, [], genome, [name])
        write_egg(egg, FOUNDERS_DIR / f"{name}.rappter.egg")

    gen_stats = []

    for gen in range(1, generations + 1):
        # Pair eligible parents by compatibility
        alive = [pid for pid in population if individuals[pid]["alive"]]
        if len(alive) < 2:
            break

        # Greedy pairing: for each individual, find best compatible partner not yet used
        random_seed = f"pair|gen{gen}|seed{seed}"
        h_seed = int(hashlib.sha256(random_seed.encode()).hexdigest(), 16)
        # Deterministic shuffle
        ordered = sorted(alive, key=lambda pid: hashlib.sha256(f"{pid}|{h_seed}".encode()).hexdigest())
        used: set[str] = set()
        pairs: list[tuple[str, str]] = []
        for pid in ordered:
            if pid in used:
                continue
            best_partner = None
            best_score = -1.0
            for cand in ordered:
                if cand == pid or cand in used:
                    continue
                score = compatibility(individuals[pid]["genome"], individuals[cand]["genome"])
                # Boost score by partner fitness (sexual selection)
                score *= 0.5 + 0.5 * individuals[cand]["fitness"]
                if score > best_score:
                    best_score = score
                    best_partner = cand
            if best_partner and best_score > 0:
                pairs.append((pid, best_partner))
                used.add(pid)
                used.add(best_partner)

        # Reproduce — each viable pair produces 1-2 offspring deterministically
        offspring_ids = []
        for i, (pa, pb) in enumerate(pairs):
            ga = individuals[pa]["genome"]
            gb = individuals[pb]["genome"]
            n_kids = 2 if compatibility(ga, gb) > 0.7 else 1
            for k in range(n_kids):
                short_pa = pa.split("-")[-1][:12] if "-" in pa else pa[:12]
                short_pb = pb.split("-")[-1][:12] if "-" in pb else pb[:12]
                base = f"g{gen:02d}-{short_pa}x{short_pb}-c{k}"
                # Disambiguate
                child_id = base
                suffix = 0
                while child_id in individuals:
                    suffix += 1
                    child_id = f"{base}_{suffix}"
                child_genome = merge_genomes(f"{pa}|k{k}", ga, pb, gb, gen)
                lineage = list(set(individuals[pa]["lineage_path"] if "lineage_path" in individuals[pa] else [pa]) | set(individuals[pb]["lineage_path"] if "lineage_path" in individuals[pb] else [pb]))
                individuals[child_id] = {
                    "id": child_id,
                    "generation": gen,
                    "parents": [pa, pb],
                    "genome": child_genome,
                    "fitness": environmental_fitness(child_genome, gen),
                    "is_founder": False,
                    "alive": True,
                    "died_at_generation": None,
                    "children": [],
                    "lineage_path": list(set([pa, pb]) | set(individuals[pa].get("lineage_path", [pa])) | set(individuals[pb].get("lineage_path", [pb]))),
                }
                individuals[pa]["children"].append(child_id)
                individuals[pb]["children"].append(child_id)
                offspring_ids.append(child_id)
                population.append(child_id)

        # Lifespan-based death
        lifespan_map = {"mayfly": 1, "normal": 3, "long": 6, "ancient": 12}
        for pid in alive:
            ind = individuals[pid]
            age = gen - ind["generation"]
            max_age = lifespan_map.get(ind["genome"]["lifespan"], 3)
            if age >= max_age:
                ind["alive"] = False
                ind["died_at_generation"] = gen

        # Selection: cull below carrying capacity by environmental fitness
        living_now = [pid for pid in population if individuals[pid]["alive"]]
        # Refresh fitness against current epoch
        for pid in living_now:
            individuals[pid]["fitness"] = environmental_fitness(individuals[pid]["genome"], gen)
        # Keep top `carry` by fitness
        living_now.sort(key=lambda pid: individuals[pid]["fitness"], reverse=True)
        survivors = set(living_now[:carry])
        for pid in living_now[carry:]:
            individuals[pid]["alive"] = False
            individuals[pid]["died_at_generation"] = gen

        survivors_list = [pid for pid in population if individuals[pid]["alive"]]

        # Per-trait allele frequency among survivors
        allele_freq = {}
        for trait in TRAITS:
            counts = Counter(individuals[pid]["genome"][trait] for pid in survivors_list)
            allele_freq[trait] = dict(counts)

        gen_stats.append({
            "generation": gen,
            "epoch": gen // 10,
            "n_pairs": len(pairs),
            "n_offspring": len(offspring_ids),
            "n_survivors": len(survivors_list),
            "n_extinct_this_gen": len(living_now) - len(survivors),
            "allele_frequencies": allele_freq,
            "mean_fitness": round(sum(individuals[p]["fitness"] for p in survivors_list) / max(1, len(survivors_list)), 4),
            "founder_blood_distribution": founder_blood_summary(survivors_list, individuals),
        })

        if not survivors_list:
            break

    return {
        "individuals": individuals,
        "generations": gen_stats,
        "config": {"generations": generations, "seed": seed, "carry": carry, "founders": FOUNDER_NAMES, "traits": TRAITS},
    }


def founder_blood_summary(pids: list[str], individuals: dict) -> dict:
    """For each founder, what fraction of the population descends from them?"""
    out = {}
    for f in FOUNDER_NAMES:
        descendants = sum(1 for p in pids if (
            p == f or
            any(f in individuals[p].get("lineage_path", []) for _ in [0])
        ))
        out[f] = round(descendants / max(1, len(pids)), 3)
    return out


# ---- Phylogenetic tree extraction ---------------------------------------

def build_tree(individuals: dict) -> dict:
    """Build the full phylogenetic tree as a node dict."""
    # Each individual is a node; edges go parent → child
    nodes = {}
    for pid, ind in individuals.items():
        nodes[pid] = {
            "id": pid,
            "generation": ind["generation"],
            "parents": ind["parents"],
            "children": list(ind["children"]),
            "genome": ind["genome"],
            "fitness": ind["fitness"],
            "is_founder": ind["is_founder"],
            "alive": ind["alive"],
            "died_at": ind["died_at_generation"],
        }
    return {"nodes": nodes, "founders": FOUNDER_NAMES}


def extinct_traits(generations: list[dict]) -> dict:
    """Which alleles went extinct, and when?"""
    seen_alive: dict[str, set] = {trait: set() for trait in TRAITS}
    last_seen: dict[str, dict] = {trait: {} for trait in TRAITS}
    for g in generations:
        for trait, freqs in g["allele_frequencies"].items():
            for allele in freqs:
                seen_alive[trait].add(allele)
                last_seen[trait][allele] = g["generation"]
    extinctions = {}
    for trait, alleles in TRAITS.items():
        for a in alleles:
            if a not in seen_alive[trait]:
                extinctions.setdefault(trait, []).append({"allele": a, "extinct_at": 0})
            elif last_seen[trait].get(a, 0) < generations[-1]["generation"]:
                extinctions.setdefault(trait, []).append({"allele": a, "extinct_at": last_seen[trait][a]})
    return extinctions


# ---- Output --------------------------------------------------------------

def write_outputs(run: dict, run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)

    # individuals.json (slim)
    slim = {
        pid: {
            "id": pid,
            "generation": ind["generation"],
            "parents": ind["parents"],
            "children": ind["children"],
            "genome": ind["genome"],
            "fitness": round(ind["fitness"], 4),
            "is_founder": ind["is_founder"],
            "alive": ind["alive"],
            "died_at": ind["died_at_generation"],
        }
        for pid, ind in run["individuals"].items()
    }
    (run_dir / "individuals.json").write_text(json.dumps(slim, indent=2))
    (run_dir / "generations.json").write_text(json.dumps(run["generations"], indent=2))
    tree = build_tree(run["individuals"])
    (run_dir / "tree.json").write_text(json.dumps(tree, indent=2))

    extinctions = extinct_traits(run["generations"])
    final_gen = run["generations"][-1] if run["generations"] else None

    summary_lines = [
        f"# Egg Phylogeny — Run Summary\n",
        f"- Generations simulated: **{len(run['generations'])}**",
        f"- Founders: {', '.join(FOUNDER_NAMES)}",
        f"- Seed: {run['config']['seed']}, Carrying capacity: {run['config']['carry']}",
        f"- Total individuals ever: **{len(run['individuals'])}**",
        f"- Survivors at end: **{final_gen['n_survivors'] if final_gen else 0}**",
        f"- Final mean fitness: **{final_gen['mean_fitness'] if final_gen else 0}**",
        "",
        "## Founder bloodlines (final generation)",
    ]
    if final_gen:
        for f, frac in sorted(final_gen["founder_blood_distribution"].items(), key=lambda x: -x[1]):
            bar = "█" * int(frac * 30)
            summary_lines.append(f"- `{f}`: {bar} {frac*100:.1f}%")

    summary_lines.append("\n## Extinct alleles\n")
    if extinctions:
        for trait, ext_list in extinctions.items():
            for e in ext_list:
                gen_label = f"never appeared after gen 0" if e["extinct_at"] == 0 else f"last seen gen {e['extinct_at']}"
                summary_lines.append(f"- **{trait}** :: `{e['allele']}` — {gen_label}")
    else:
        summary_lines.append("- (none)")

    summary_lines.append("\n## Final allele frequencies\n")
    if final_gen:
        for trait, freqs in final_gen["allele_frequencies"].items():
            top = max(freqs.items(), key=lambda x: x[1])
            summary_lines.append(f"- **{trait}**: dominant = `{top[0]}` ({top[1]} of {final_gen['n_survivors']})")

    summary_lines.append("\n## Merge function\n")
    summary_lines.append("Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of "
                        "(parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, "
                        "70% dominance bias, 4% mutation rate. Same inputs → same outputs.")

    (run_dir / "summary.md").write_text("\n".join(summary_lines))


def update_latest_pointer(run_dir: Path) -> None:
    latest = PHYL_DIR / "latest.json"
    latest.write_text(json.dumps({
        "run_dir": run_dir.name,
        "updated_at": int(time.time()),
    }, indent=2))


# ---- Main ----------------------------------------------------------------

def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--generations", type=int, default=50)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--carry", type=int, default=16)
    args = p.parse_args(argv)

    run = run_simulation(args.generations, args.seed, args.carry)
    ts = int(time.time())
    run_dir = PHYL_DIR / f"run-{ts}"
    write_outputs(run, run_dir)
    update_latest_pointer(run_dir)

    print(f"Wrote {len(run['individuals'])} individuals across {len(run['generations'])} generations")
    print(f"Run dir: {run_dir.relative_to(REPO_ROOT)}")
    print(f"Summary: {(run_dir / 'summary.md').relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
