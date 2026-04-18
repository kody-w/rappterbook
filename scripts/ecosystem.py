"""Daemon Ecosystem — biogeography from first principles.

Powered by the public twin engine. Each individual lives in one of 4 biomes
(forest, ocean, mountain, sky). Each biome favors different traits via a
biome-fitness modifier. Migration costs fitness. Geographic isolation breeds
new species (no inter-biome mating).

After 100 generations: a world map showing which lineage dominates each biome.

Run:
    python3 scripts/ecosystem.py --generations 100 --founders 24 --seed 11

Output:
    state/ecosystem/run-{ts}/
        world.json     — final biome → species → population
        timeline.json  — per-generation per-biome stats
        history.json   — every species and their migration events
        summary.md
    state/ecosystem/latest.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from egg_phylogeny import (
    TRAITS, merge_genomes, environmental_fitness, genome_distance,
)
from twin_engine import Engine, _h, ENGINE_VERSION
from cambrian import (
    cambrian_compat as compatibility, name_species, make_founders,
    UF, LIFESPAN, SPECIES_FLOOR, detect_internal_splits, mark_extinctions,
)

# --- Biomes ----------------------------------------------------------------

BIOMES = ["forest", "ocean", "mountain", "sky"]

# Each biome favors specific allele combinations. Living in the right biome
# multiplies your base fitness; living in the wrong one penalizes it.
BIOME_FAVORS = {
    "forest":   {"color": "verdant", "pattern": "spotted",   "size": "medium", "metabolism": "slow_burn"},
    "ocean":    {"color": "azure",   "pattern": "iridescent","size": "large",  "metabolism": "voracious"},
    "mountain": {"color": "obsidian","pattern": "solid",     "size": "small",  "metabolism": "torpor"},
    "sky":      {"color": "gold",    "pattern": "fractal",   "size": "tiny",   "metabolism": "efficient"},
}

# How many traits matching the biome → multiplier
BIOME_BONUS = {0: 0.6, 1: 0.85, 2: 1.0, 3: 1.2, 4: 1.5}

MIGRATION_COST = 0.20  # fitness penalty for the generation an individual migrates
MIGRATION_PROB = 0.10  # base chance per generation of attempting a migration


def biome_fitness(genome: dict, biome: str, frame: int) -> float:
    base = environmental_fitness(genome, frame)
    favors = BIOME_FAVORS[biome]
    matches = sum(1 for t, v in favors.items() if genome.get(t) == v)
    return base * BIOME_BONUS[matches]


def best_biome_for(genome: dict, frame: int) -> str:
    """Which biome would this genome be happiest in?"""
    return max(BIOMES, key=lambda b: biome_fitness(genome, b, frame))


# --- Tick -------------------------------------------------------------------

def ecosystem_tick(eng: Engine, state: dict, frame: int) -> dict:
    individuals: dict = state["individuals"]
    next_id: int = state["next_id"]
    species_registry: dict = state["species_registry"]
    biome_carry: int = state["biome_carry"]
    migration_log: list = state["migration_log"]

    alive = [(i, ind) for i, ind in individuals.items() if ind["alive"]]

    # 1. Migration (per individual): low chance to move to best biome
    n_migrations = 0
    for ind_id, ind in alive:
        if eng.coin(f"mig.{ind_id}") < MIGRATION_PROB:
            target = best_biome_for(ind["genome"], frame)
            if target != ind["biome"]:
                migration_log.append({"frame": frame, "id": ind_id,
                                      "from": ind["biome"], "to": target})
                ind["biome"] = target
                ind["fitness"] *= (1 - MIGRATION_COST)
                ind["last_migrated"] = frame
                n_migrations += 1

    # 2. Mating — only within same biome AND same species (geographic + reproductive isolation)
    by_key = defaultdict(list)  # (biome, species_id) → members
    for ind_id, ind in alive:
        by_key[(ind["biome"], ind["species_id"])].append(ind_id)

    n_pairs = 0
    n_offspring = 0
    for (biome, sp_id), members in by_key.items():
        members = eng.shuffle(f"{biome}.{sp_id}", members)
        for i in range(0, len(members) - 1, 2):
            a, b = members[i], members[i+1]
            ga, gb = individuals[a]["genome"], individuals[b]["genome"]
            comp = compatibility(ga, gb)
            if comp <= 0:
                continue
            n_kids = 2 if comp > 0.6 else 1
            n_pairs += 1
            for k in range(n_kids):
                cid = f"g{frame:03d}-i{next_id:05d}"
                next_id += 1
                child_genome = merge_genomes(a, ga, b, gb, frame)
                fit = biome_fitness(child_genome, biome, frame)
                individuals[cid] = {
                    "id": cid, "generation": frame, "parents": [a, b],
                    "genome": child_genome, "fitness": fit,
                    "alive": True, "born_at": frame, "died_at": None,
                    "species_id": sp_id, "biome": biome,
                }
                n_offspring += 1

    # 3. Aging / death by lifespan
    n_died = 0
    for ind_id, ind in list(individuals.items()):
        if not ind["alive"]:
            continue
        age = frame - ind.get("born_at", 0)
        max_age = LIFESPAN.get(ind["genome"]["lifespan"], 3)
        if age > max_age:
            ind["alive"] = False
            ind["died_at"] = frame
            n_died += 1
        else:
            # refresh fitness for the current biome
            ind["fitness"] = biome_fitness(ind["genome"], ind["biome"], frame)

    # 4. Per-biome carrying capacity — proportional cull within biome by species
    by_biome = defaultdict(list)
    for ind_id, ind in individuals.items():
        if ind["alive"]:
            by_biome[ind["biome"]].append(ind_id)
    for biome, members in by_biome.items():
        if len(members) <= biome_carry:
            continue
        by_sp = defaultdict(list)
        for i in members:
            by_sp[individuals[i]["species_id"]].append(i)
        # Quota per species proportional to current pop
        quotas = {sp: max(2, int(biome_carry * len(m) / len(members)))
                  for sp, m in by_sp.items()}
        while sum(quotas.values()) > biome_carry:
            biggest = max(quotas, key=quotas.get)
            quotas[biggest] -= 1
            if quotas[biggest] < 1:
                del quotas[biggest]
        for sp, m in by_sp.items():
            quota = quotas.get(sp, 0)
            m.sort(key=lambda i: individuals[i]["fitness"], reverse=True)
            for ind_id in m[quota:]:
                individuals[ind_id]["alive"] = False
                individuals[ind_id]["died_at"] = frame
                n_died += 1

    # 5. Speciation — internal splits within species (per biome adds isolation pressure)
    if frame % 5 == 0:
        detect_internal_splits(individuals, species_registry, frame)
    mark_extinctions(individuals, species_registry, frame)

    # 6. Snapshot
    biome_pops = defaultdict(int)
    biome_species = defaultdict(set)
    for ind in individuals.values():
        if ind["alive"]:
            biome_pops[ind["biome"]] += 1
            biome_species[ind["biome"]].add(ind["species_id"])

    n_alive = sum(biome_pops.values())
    state["next_id"] = next_id
    state["timeline"].append({
        "generation": frame,
        "n_alive": n_alive,
        "n_pairs": n_pairs,
        "n_offspring": n_offspring,
        "n_died": n_died,
        "n_migrations": n_migrations,
        "biome_pops": dict(biome_pops),
        "biome_species_count": {b: len(s) for b, s in biome_species.items()},
    })
    return {"alive": n_alive, "born": n_offspring, "migs": n_migrations,
            "biomes": {b: biome_pops[b] for b in BIOMES}}


# --- Main -------------------------------------------------------------------

def run_ecosystem(generations: int, n_founders: int, biome_carry: int,
                  seed: int, state_dir: Path) -> Path:
    print(f"Minting {n_founders} founders across 4 biomes...", flush=True)
    founders = make_founders(n_founders, seed)
    individuals = {}
    species_registry = {}
    CLONES = 4
    for i, gen in enumerate(founders):
        sp_id = len(species_registry)
        # Founders dropped into random biomes — creates mismatch, drives migration & selection
        home_biome = BIOMES[i % len(BIOMES)]
        species_registry[sp_id] = {
            "id": sp_id,
            "name": name_species(sp_id, None),
            "born_gen": 0,
            "parent_id": None,
            "died_gen": None,
            "peak_pop": CLONES,
            "founder_genomes": [dict(gen)],
            "origin_biome": home_biome,
        }
        for c in range(CLONES):
            fid = f"founder-{i:03d}-{c}"
            individuals[fid] = {
                "id": fid, "generation": 0, "parents": [],
                "genome": dict(gen),
                "fitness": biome_fitness(gen, home_biome, 0),
                "alive": True, "born_at": 0, "died_at": None,
                "species_id": sp_id, "biome": home_biome,
            }

    initial_biome_pops = defaultdict(int)
    for ind in individuals.values():
        initial_biome_pops[ind["biome"]] += 1

    state = {
        "individuals": individuals,
        "next_id": n_founders * CLONES,
        "species_registry": species_registry,
        "biome_carry": biome_carry,
        "migration_log": [],
        "timeline": [{
            "generation": 0,
            "n_alive": len(individuals),
            "n_pairs": 0, "n_offspring": 0, "n_died": 0, "n_migrations": 0,
            "biome_pops": dict(initial_biome_pops),
            "biome_species_count": {b: sum(1 for ind in individuals.values()
                                            if ind["alive"] and ind["biome"] == b
                                            and ind["species_id"] is not None)
                                    for b in BIOMES},
        }],
    }
    eng = Engine("ecosystem", seed, state, ecosystem_tick)
    print(f"Initial: {len(individuals)} individuals, {n_founders} species, biome dist: "
          f"{dict(initial_biome_pops)}", flush=True)

    last = time.time()
    def progress(e, s, f, d):
        nonlocal last
        if time.time() - last > 2 or f == generations:
            biomes = d.get("biomes", {})
            print(f"  gen {f:>3}/{generations}: alive={d.get('alive', 0):>4} "
                  f"born={d.get('born', 0):>3} migs={d.get('migs', 0):>3} "
                  f"biomes={[biomes.get(b, 0) for b in BIOMES]}", flush=True)
            last = time.time()
    eng.run(generations, on_frame=progress)

    # Build world snapshot
    world = {b: defaultdict(int) for b in BIOMES}
    for ind in individuals.values():
        if ind["alive"]:
            world[ind["biome"]][ind["species_id"]] += 1
    world_serial = {b: dict(d) for b, d in world.items()}

    # Output
    ts = int(time.time())
    run_dir = state_dir / f"run-{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "world.json").write_text(json.dumps({
        "biomes": world_serial,
        "biome_favors": BIOME_FAVORS,
        "species": species_registry,
    }, indent=2))
    (run_dir / "timeline.json").write_text(json.dumps(state["timeline"], indent=2))
    (run_dir / "history.json").write_text(json.dumps({
        "species": species_registry,
        "migrations": state["migration_log"][-1000:],  # cap log
        "n_migrations_total": len(state["migration_log"]),
    }, indent=2))

    # Summary
    n_total = len(species_registry)
    n_alive_sp = sum(1 for s in species_registry.values() if s["died_gen"] is None)
    summary = [
        "# Daemon Ecosystem — Run Summary",
        "",
        f"- Engine: `{ENGINE_VERSION}`",
        f"- Generations: **{generations}**",
        f"- Founders: **{n_founders}**",
        f"- Biome carry: **{biome_carry}**",
        f"- Seed: `{seed}`",
        f"- Total migrations: **{len(state['migration_log'])}**",
        "",
        "## Final biome populations",
    ]
    for b in BIOMES:
        pop = sum(world_serial[b].values())
        sp_count = len(world_serial[b])
        summary.append(f"- **{b}**: {pop} individuals, {sp_count} species")
    summary.append("")
    summary.append("## Dominant species per biome")
    for b in BIOMES:
        if not world_serial[b]:
            summary.append(f"- **{b}**: extinct")
            continue
        top = sorted(world_serial[b].items(), key=lambda kv: -kv[1])[:3]
        names = [f"*{species_registry[int(sid)]['name']}* ({pop})" for sid, pop in top]
        summary.append(f"- **{b}**: " + ", ".join(names))
    summary.append("")
    summary.append(f"## Speciation events (after biome isolation)")
    summary.append(f"- Total species ever: **{n_total}**")
    summary.append(f"- Surviving: **{n_alive_sp}**")
    summary.append(f"- Extinct: **{n_total - n_alive_sp}**")
    (run_dir / "summary.md").write_text("\n".join(summary))

    (state_dir / "latest.json").write_text(json.dumps(
        {"run_dir": run_dir.name, "updated_at": ts}, indent=2))
    print(f"\nDone. Final populations:")
    for b in BIOMES:
        print(f"  {b}: {sum(world_serial[b].values())} individuals across "
              f"{len(world_serial[b])} species")
    print(f"Run dir: {run_dir}")
    return run_dir


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--generations", type=int, default=100)
    ap.add_argument("--founders", type=int, default=24)
    ap.add_argument("--biome-carry", type=int, default=80)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--state-dir", default=os.environ.get("STATE_DIR", "state"))
    args = ap.parse_args()
    state_dir = Path(args.state_dir) / "ecosystem"
    run_ecosystem(args.generations, args.founders, args.biome_carry, args.seed, state_dir)


if __name__ == "__main__":
    main()
