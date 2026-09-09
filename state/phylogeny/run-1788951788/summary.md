# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 247, Carrying capacity: 40
- Total individuals ever: **1991**
- Survivors at end: **40**
- Final mean fitness: **0.7537**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `azure` — last seen gen 55
- **color** :: `verdant` — last seen gen 17
- **pattern** :: `iridescent` — last seen gen 40
- **pattern** :: `fractal` — last seen gen 30
- **size** :: `giant` — last seen gen 56
- **temperament** :: `curious` — last seen gen 58
- **temperament** :: `cautious` — last seen gen 29
- **temperament** :: `aggressive` — last seen gen 56
- **temperament** :: `chaotic` — last seen gen 58
- **sociability** :: `solitary` — last seen gen 41
- **sociability** :: `pair` — last seen gen 50
- **sociability** :: `swarm` — last seen gen 23
- **cognition** :: `deep_thinker` — last seen gen 58
- **cognition** :: `rapid_reactor` — last seen gen 41
- **cognition** :: `memory_hoarder` — last seen gen 55
- **lifespan** :: `mayfly` — last seen gen 18
- **lifespan** :: `normal` — last seen gen 8
- **lifespan** :: `long` — last seen gen 19

## Final allele frequencies

- **color**: dominant = `crimson` (35 of 40)
- **pattern**: dominant = `solid` (24 of 40)
- **size**: dominant = `large` (16 of 40)
- **temperament**: dominant = `peaceful` (40 of 40)
- **sociability**: dominant = `pack` (40 of 40)
- **cognition**: dominant = `pattern_matcher` (40 of 40)
- **metabolism**: dominant = `efficient` (25 of 40)
- **lifespan**: dominant = `ancient` (40 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.