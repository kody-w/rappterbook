"""Cambrian Explosion — 100 founders, 500 generations, speciation tracked.

Powered by the public twin engine. Reuses the genome + merge function from
egg_phylogeny.py but replaces the population model with one that:

  * mints 100 maximally-spread founders (random sample of all 5^4 * 4^4 = 160k genomes)
  * detects species each generation via union-find on the compatibility graph
  * tracks species birth (split events) and death (extinctions)
  * names species deterministically from a binomial-style word list
  * outputs a cladogram: which species came from which, when they split

Run:
    python3 scripts/cambrian.py --generations 500 --founders 100 --carry 200 --seed 7

Output:
    state/cambrian/run-{ts}/
        species.json     — every species ever (id, name, born_gen, died_gen, parent, members)
        timeline.json    — per-generation: alive species, populations, fitness
        cladogram.json   — tree shape ready for rendering
        summary.md
    state/cambrian/latest.json
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
    TRAITS, merge_genomes, compatibility as base_compat, environmental_fitness,
    genome_distance,
)
from twin_engine import Engine, _h, ENGINE_VERSION


# Cambrian uses STRICTER compatibility — reproductive isolation kicks in
# when two genomes differ on more than HARD_ISOLATION traits. This is what
# allows species to actually form. base_compat had a floor of 0.2 to keep
# the small phylogeny demo from going extinct; here we want real barriers.

HARD_ISOLATION = 5  # if 5+ traits differ (out of 8), pair is reproductively isolated


def cambrian_compat(g1: dict, g2: dict) -> float:
    d = genome_distance(g1, g2)
    if d >= HARD_ISOLATION:
        return 0.0       # speciation barrier
    # Allow clone/near-clone mating in early gens — mutation creates the variation
    if d == 0:
        return 0.5
    return base_compat(g1, g2)


# Patch the compat used by detect_species below
compatibility = cambrian_compat

# --- Naming -----------------------------------------------------------------

GENUS_PREFIXES = ["Aetho", "Bryo", "Chrono", "Dendro", "Eo", "Ferro", "Glyco", "Helio",
                  "Iso", "Kryo", "Litho", "Myco", "Nyct", "Ophio", "Pyro", "Quasi",
                  "Rhyno", "Stego", "Therm", "Ultro", "Verm", "Xeno", "Yotta", "Zoa"]
GENUS_ROOTS = ["saur", "ptera", "phyte", "morph", "drake", "lith", "phant", "cere",
               "mantis", "sphinx", "wyrm", "naga", "korax", "loris", "veles", "draco"]
SPECIES_EPITHETS = ["primus", "verum", "magnus", "minor", "borealis", "australis",
                    "pacificus", "obscurus", "lucidus", "ferox", "placidus", "rapidus",
                    "elegans", "rusticus", "nobilis", "vulgaris", "sapiens", "sylvestris",
                    "antiquus", "novus", "mirabilis", "gracilis", "robustus", "compactus"]


def name_species(species_id: int, parent_name: str | None) -> str:
    if parent_name is None:
        # Founder species — fresh genus
        gp = GENUS_PREFIXES[species_id % len(GENUS_PREFIXES)]
        gr = GENUS_ROOTS[(species_id // len(GENUS_PREFIXES)) % len(GENUS_ROOTS)]
        ep = SPECIES_EPITHETS[species_id % len(SPECIES_EPITHETS)]
        return f"{gp}{gr} {ep}"
    # Daughter species — same genus, new epithet
    parts = parent_name.split()
    genus = parts[0]
    new_ep = SPECIES_EPITHETS[(species_id * 7 + 11) % len(SPECIES_EPITHETS)]
    if new_ep == parts[1]:
        new_ep = SPECIES_EPITHETS[(species_id * 7 + 23) % len(SPECIES_EPITHETS)]
    return f"{genus} {new_ep}"


# --- Founder generation -----------------------------------------------------

def make_founders(n: int, seed: int) -> list[dict]:
    """Generate n maximally-spread genomes. Greedy farthest-point sampling."""
    all_traits = list(TRAITS.keys())
    # Build deterministic candidate pool
    candidates = []
    for i in range(n * 8):
        gen = {}
        for t in all_traits:
            opts = TRAITS[t]
            idx = int(_h("cambrian", str(seed), str(i), t)[:13], 16) % len(opts)
            gen[t] = opts[idx]
        # Dedup by tuple
        if gen not in candidates:
            candidates.append(gen)
    # Greedy: start with first, repeatedly pick the candidate maximizing min distance
    chosen = [candidates[0]]
    while len(chosen) < n and len(chosen) < len(candidates):
        best = None
        best_dist = -1
        for c in candidates:
            if c in chosen:
                continue
            d = min(1 - compatibility(c, x) for x in chosen)
            if d > best_dist:
                best_dist = d
                best = c
        if best is None:
            break
        chosen.append(best)
    return chosen[:n]


# --- Speciation: union-find on compatibility graph -------------------------

class UF:
    def __init__(self, items):
        self.p = {i: i for i in items}
    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x
    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


SPECIES_FLOOR = 0.01  # any positive compat = same species (the cambrian_compat does the gating)


def detect_species(individuals: dict) -> list[list[str]]:
    """For internal split detection only — NOT for reassigning species."""
    alive = [i for i, ind in individuals.items() if ind["alive"]]
    uf = UF(alive)
    for i, a in enumerate(alive):
        for b in alive[i+1:]:
            if compatibility(individuals[a]["genome"], individuals[b]["genome"]) >= SPECIES_FLOOR:
                uf.union(a, b)
    groups = defaultdict(list)
    for ind_id in alive:
        groups[uf.find(ind_id)].append(ind_id)
    return list(groups.values())


SPECIES_FLOOR = 0.01


def detect_internal_splits(individuals, species_registry, frame):
    """For each species, check if its alive members form multiple disjoint
    compatibility clusters. If so, split off the smaller clusters as new species.
    """
    by_sp = defaultdict(list)
    for ind_id, ind in individuals.items():
        if ind["alive"] and ind.get("species_id") is not None:
            by_sp[ind["species_id"]].append(ind_id)

    new_species_births = []
    for sp_id, members in by_sp.items():
        if len(members) < 4:
            continue
        # Cluster within this species
        uf = UF(members)
        for i, a in enumerate(members):
            for b in members[i+1:]:
                if compatibility(individuals[a]["genome"], individuals[b]["genome"]) >= SPECIES_FLOOR:
                    uf.union(a, b)
        clusters = defaultdict(list)
        for m in members:
            clusters[uf.find(m)].append(m)
        if len(clusters) <= 1:
            continue  # still one cohesive species
        # Speciation event! Largest cluster keeps original species_id; others spin off
        cluster_list = sorted(clusters.values(), key=len, reverse=True)
        for new_cluster in cluster_list[1:]:
            if len(new_cluster) < 2:
                continue  # ignore singletons (they'll die out)
            new_id = len(species_registry)
            parent_name = species_registry[sp_id]["name"]
            species_registry[new_id] = {
                "id": new_id,
                "name": name_species(new_id, parent_name),
                "born_gen": frame,
                "parent_id": sp_id,
                "died_gen": None,
                "peak_pop": len(new_cluster),
                "founder_genomes": [individuals[m]["genome"] for m in new_cluster[:3]],
            }
            for m in new_cluster:
                individuals[m]["species_id"] = new_id
            new_species_births.append(new_id)
    return new_species_births


def mark_extinctions(individuals, species_registry, frame):
    alive_species = set()
    for ind in individuals.values():
        if ind["alive"] and ind.get("species_id") is not None:
            alive_species.add(ind["species_id"])
    for sid, sp in species_registry.items():
        if sp["died_gen"] is None and sid not in alive_species and sp["born_gen"] < frame:
            sp["died_gen"] = frame


# --- Tick: one generation of life -------------------------------------------

LIFESPAN = {"mayfly": 1, "normal": 3, "long": 6, "ancient": 12}


def cambrian_tick(eng: Engine, state: dict, frame: int) -> dict:
    individuals: dict = state["individuals"]
    carry: int = state["carry"]
    next_id: int = state["next_id"]
    species_registry: dict = state["species_registry"]

    alive = [(i, ind) for i, ind in individuals.items() if ind["alive"]]
    # Pair within species (compatible by definition)
    by_species = defaultdict(list)
    for ind_id, ind in alive:
        by_species[ind.get("species_id", -1)].append(ind_id)

    n_pairs = 0
    n_offspring = 0
    for sp, members in by_species.items():
        members = eng.shuffle(f"sp{sp}", members)
        # pair them up
        for i in range(0, len(members) - 1, 2):
            a, b = members[i], members[i+1]
            ga, gb = individuals[a]["genome"], individuals[b]["genome"]
            comp = compatibility(ga, gb)
            if comp <= 0:
                continue  # reproductively isolated even within "species" label (shouldn't happen often)
            n_kids = 2 if comp > 0.6 else 1
            n_pairs += 1
            for k in range(n_kids):
                cid = f"g{frame:03d}-i{next_id:05d}"
                next_id += 1
                child_genome = merge_genomes(a, ga, b, gb, frame)
                fit = environmental_fitness(child_genome, frame)
                individuals[cid] = {
                    "id": cid, "generation": frame, "parents": [a, b],
                    "genome": child_genome, "fitness": fit,
                    "alive": True, "born_at": frame, "died_at": None,
                    "species_id": individuals[a]["species_id"],  # inherit parent's species
                }
                n_offspring += 1

    # Aging / death
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

    # Cull to carrying capacity — proportional by species (don't wipe out small species)
    survivors = [i for i, ind in individuals.items() if ind["alive"]]
    if len(survivors) > carry:
        # Group survivors by current species (or by genome cluster if unset)
        by_sp = defaultdict(list)
        for i in survivors:
            by_sp[individuals[i].get("species_id", -1)].append(i)
        # Each species gets a carry quota proportional to its population
        quotas = {sp: max(2, int(carry * len(members) / len(survivors)))
                  for sp, members in by_sp.items()}
        # Trim quotas down so total <= carry
        while sum(quotas.values()) > carry:
            # Drop one from the largest quota
            biggest = max(quotas, key=quotas.get)
            quotas[biggest] -= 1
            if quotas[biggest] < 1:
                del quotas[biggest]
        # Cull within each species — keep top fitness
        for sp, members in by_sp.items():
            quota = quotas.get(sp, 0)
            members.sort(key=lambda i: individuals[i]["fitness"], reverse=True)
            for ind_id in members[quota:]:
                individuals[ind_id]["alive"] = False
                individuals[ind_id]["died_at"] = frame
                n_died += 1

    # Detect speciation events (splits within existing species) every 5 frames
    if frame % 5 == 0:
        detect_internal_splits(individuals, state["species_registry"], frame)
    mark_extinctions(individuals, state["species_registry"], frame)

    # Snapshot per-generation timeline entry
    n_alive = sum(1 for i, ind in individuals.items() if ind["alive"])
    mean_fit = (sum(individuals[i]["fitness"] for i in individuals if individuals[i]["alive"])
                / max(1, n_alive))
    species_pops = defaultdict(int)
    for i, ind in individuals.items():
        if ind["alive"]:
            species_pops[ind["species_id"]] += 1
    # Update peak_pop
    for sp_id, pop in species_pops.items():
        if sp_id is not None and sp_id in state["species_registry"]:
            state["species_registry"][sp_id]["peak_pop"] = max(
                state["species_registry"][sp_id]["peak_pop"], pop)

    state["next_id"] = next_id
    state["timeline"].append({
        "generation": frame,
        "n_alive": n_alive,
        "n_pairs": n_pairs,
        "n_offspring": n_offspring,
        "n_died": n_died,
        "mean_fitness": round(mean_fit, 4),
        "n_species": len(species_pops),
        "species_pops": dict(species_pops),
    })
    return {"alive": n_alive, "species": len(species_pops),
            "offspring": n_offspring, "died": n_died}


# --- Main -------------------------------------------------------------------

def run_cambrian(generations: int, n_founders: int, carry: int, seed: int,
                 state_dir: Path) -> Path:
    print(f"Minting {n_founders} founders...", flush=True)
    founders = make_founders(n_founders, seed)
    individuals = {}
    species_registry = {}
    # Seed 3 clones per founder so each starting species has a viable population
    CLONES_PER_FOUNDER = 3
    for i, gen in enumerate(founders):
        for c in range(CLONES_PER_FOUNDER):
            fid = f"founder-{i:03d}-{c}"
            individuals[fid] = {
                "id": fid, "generation": 0, "parents": [],
                "genome": dict(gen), "fitness": environmental_fitness(gen, 0),
                "alive": True, "born_at": 0, "died_at": None, "species_id": None,
            }
    # Each founder genome → one species (its 3 clones are the founding members)
    for i, gen in enumerate(founders):
        sp_id = len(species_registry)
        species_registry[sp_id] = {
            "id": sp_id,
            "name": name_species(sp_id, None),
            "born_gen": 0,
            "parent_id": None,
            "died_gen": None,
            "peak_pop": CLONES_PER_FOUNDER,
            "founder_genomes": [dict(gen)],
        }
        for c in range(CLONES_PER_FOUNDER):
            fid = f"founder-{i:03d}-{c}"
            individuals[fid]["species_id"] = sp_id
    n_starting_species = len(species_registry)

    state = {
        "individuals": individuals,
        "carry": carry,
        "next_id": n_founders * CLONES_PER_FOUNDER,
        "species_registry": species_registry,
        "timeline": [{"generation": 0,
                      "n_alive": len(individuals), "n_pairs": 0, "n_offspring": 0, "n_died": 0,
                      "mean_fitness": round(sum(i["fitness"] for i in individuals.values())/len(individuals), 4),
                      "n_species": n_starting_species,
                      "species_pops": {sp: CLONES_PER_FOUNDER for sp in range(n_starting_species)}}],
    }
    eng = Engine("cambrian", seed, state, cambrian_tick)
    print(f"Initial: {len(individuals)} individuals → {n_starting_species} starting species", flush=True)

    last_report = time.time()
    def progress(e, s, f, d):
        nonlocal last_report
        if time.time() - last_report > 2 or f == generations:
            print(f"  gen {f:>3}/{generations}: alive={d.get('alive', '?'):>4} "
                  f"species={d.get('species', '?'):>3} born={d.get('offspring', 0):>3}", flush=True)
            last_report = time.time()
    eng.run(generations, on_frame=progress)

    # Mark still-alive species
    for sp in species_registry.values():
        if sp["died_gen"] is None:
            sp["last_seen_gen"] = generations

    # Build cladogram (tree of species lineages)
    cladogram = {"nodes": species_registry, "roots": [
        sid for sid, sp in species_registry.items() if sp["parent_id"] is None]}

    # Output
    ts = int(time.time())
    run_dir = state_dir / f"run-{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "species.json").write_text(json.dumps(species_registry, indent=2))
    (run_dir / "timeline.json").write_text(json.dumps(state["timeline"], indent=2))
    (run_dir / "cladogram.json").write_text(json.dumps(cladogram, indent=2))

    # Summary
    n_total = len(species_registry)
    n_extinct = sum(1 for s in species_registry.values() if s["died_gen"] is not None)
    n_alive = n_total - n_extinct
    summary = [
        "# Cambrian Explosion — Run Summary",
        "",
        f"- Engine: `{ENGINE_VERSION}`",
        f"- Generations: **{generations}**",
        f"- Founders: **{n_founders}**",
        f"- Carrying capacity: **{carry}**",
        f"- Random seed: `{seed}`",
        "",
        "## Species totals",
        f"- Total species ever: **{n_total}**",
        f"- Surviving at end: **{n_alive}**",
        f"- Extinct: **{n_extinct}**",
        f"- Speciation events (splits): **{sum(1 for s in species_registry.values() if s['parent_id'] is not None)}**",
        "",
        "## Surviving species",
    ]
    for sp in sorted(species_registry.values(), key=lambda s: -s["peak_pop"])[:30]:
        if sp["died_gen"] is None:
            summary.append(f"- *{sp['name']}* — born gen {sp['born_gen']}, peak pop {sp['peak_pop']}")
    summary.append("")
    summary.append("## Notable extinctions")
    extinct = [s for s in species_registry.values() if s["died_gen"] is not None]
    extinct.sort(key=lambda s: -(s.get("died_gen", 0) - s.get("born_gen", 0)))
    for sp in extinct[:15]:
        lifespan = sp["died_gen"] - sp["born_gen"]
        summary.append(f"- *{sp['name']}* — gen {sp['born_gen']}–{sp['died_gen']} ({lifespan} gens, peak pop {sp['peak_pop']})")
    (run_dir / "summary.md").write_text("\n".join(summary))

    # Latest pointer
    (state_dir / "latest.json").write_text(json.dumps(
        {"run_dir": run_dir.name, "updated_at": ts}, indent=2))
    print(f"\nDone. {n_total} species ever. {n_alive} surviving. {n_extinct} extinct.")
    print(f"Run dir: {run_dir}")
    return run_dir


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--generations", type=int, default=500)
    ap.add_argument("--founders", type=int, default=100)
    ap.add_argument("--carry", type=int, default=200)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--state-dir", default=os.environ.get("STATE_DIR", "state"))
    args = ap.parse_args()
    state_dir = Path(args.state_dir) / "cambrian"
    run_cambrian(args.generations, args.founders, args.carry, args.seed, state_dir)


if __name__ == "__main__":
    main()
