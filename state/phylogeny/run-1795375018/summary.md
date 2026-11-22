# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 490, Carrying capacity: 40
- Total individuals ever: **1743**
- Survivors at end: **40**
- Final mean fitness: **0.775**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`:  0.0%
- `gold-storm`:  0.0%

## Extinct alleles

- **color** :: `azure` — last seen gen 56
- **color** :: `gold` — last seen gen 53
- **color** :: `obsidian` — last seen gen 56
- **pattern** :: `iridescent` — last seen gen 44
- **size** :: `medium` — last seen gen 11
- **size** :: `giant` — last seen gen 55
- **temperament** :: `cautious` — last seen gen 32
- **temperament** :: `aggressive` — last seen gen 59
- **temperament** :: `chaotic` — last seen gen 32
- **sociability** :: `solitary` — last seen gen 57
- **sociability** :: `pair` — last seen gen 54
- **cognition** :: `rapid_reactor` — last seen gen 57
- **cognition** :: `memory_hoarder` — last seen gen 23
- **lifespan** :: `mayfly` — last seen gen 58
- **lifespan** :: `normal` — last seen gen 19

## Final allele frequencies

- **color**: dominant = `crimson` (39 of 40)
- **pattern**: dominant = `solid` (34 of 40)
- **size**: dominant = `small` (27 of 40)
- **temperament**: dominant = `peaceful` (39 of 40)
- **sociability**: dominant = `pack` (33 of 40)
- **cognition**: dominant = `deep_thinker` (30 of 40)
- **metabolism**: dominant = `voracious` (31 of 40)
- **lifespan**: dominant = `ancient` (36 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.