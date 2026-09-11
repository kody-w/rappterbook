# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 256, Carrying capacity: 40
- Total individuals ever: **1916**
- Survivors at end: **40**
- Final mean fitness: **0.7537**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `verdant` — last seen gen 59
- **color** :: `gold` — last seen gen 28
- **color** :: `obsidian` — last seen gen 43
- **pattern** :: `fractal` — last seen gen 59
- **size** :: `small` — last seen gen 52
- **size** :: `medium` — last seen gen 58
- **size** :: `large` — last seen gen 35
- **temperament** :: `cautious` — last seen gen 35
- **temperament** :: `aggressive` — last seen gen 59
- **temperament** :: `chaotic` — last seen gen 59
- **sociability** :: `solitary` — last seen gen 51
- **sociability** :: `pair` — last seen gen 51
- **cognition** :: `rapid_reactor` — last seen gen 58
- **metabolism** :: `efficient` — last seen gen 29
- **lifespan** :: `mayfly` — last seen gen 1
- **lifespan** :: `normal` — last seen gen 52
- **lifespan** :: `long` — last seen gen 36

## Final allele frequencies

- **color**: dominant = `crimson` (32 of 40)
- **pattern**: dominant = `solid` (33 of 40)
- **size**: dominant = `tiny` (39 of 40)
- **temperament**: dominant = `curious` (22 of 40)
- **sociability**: dominant = `pack` (39 of 40)
- **cognition**: dominant = `deep_thinker` (23 of 40)
- **metabolism**: dominant = `voracious` (38 of 40)
- **lifespan**: dominant = `ancient` (40 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.