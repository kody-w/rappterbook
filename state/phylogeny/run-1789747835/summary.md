# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 283, Carrying capacity: 40
- Total individuals ever: **1616**
- Survivors at end: **40**
- Final mean fitness: **0.785**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `crimson` — last seen gen 13
- **color** :: `gold` — last seen gen 42
- **color** :: `obsidian` — last seen gen 17
- **pattern** :: `iridescent` — last seen gen 16
- **pattern** :: `fractal` — last seen gen 43
- **size** :: `large` — last seen gen 43
- **temperament** :: `cautious` — last seen gen 32
- **temperament** :: `aggressive` — last seen gen 33
- **temperament** :: `chaotic` — last seen gen 42
- **sociability** :: `solitary` — last seen gen 49
- **sociability** :: `pair` — last seen gen 15
- **cognition** :: `rapid_reactor` — last seen gen 43
- **lifespan** :: `mayfly` — last seen gen 5
- **lifespan** :: `normal` — last seen gen 59

## Final allele frequencies

- **color**: dominant = `azure` (36 of 40)
- **pattern**: dominant = `solid` (37 of 40)
- **size**: dominant = `tiny` (31 of 40)
- **temperament**: dominant = `peaceful` (33 of 40)
- **sociability**: dominant = `pack` (38 of 40)
- **cognition**: dominant = `deep_thinker` (26 of 40)
- **metabolism**: dominant = `voracious` (30 of 40)
- **lifespan**: dominant = `ancient` (35 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.