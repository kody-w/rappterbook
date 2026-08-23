# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 187, Carrying capacity: 40
- Total individuals ever: **1757**
- Survivors at end: **40**
- Final mean fitness: **0.7662**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `azure` — last seen gen 53
- **color** :: `gold` — last seen gen 54
- **color** :: `obsidian` — last seen gen 7
- **pattern** :: `fractal` — last seen gen 54
- **size** :: `tiny` — last seen gen 43
- **temperament** :: `curious` — last seen gen 52
- **sociability** :: `pair` — last seen gen 57
- **sociability** :: `swarm` — last seen gen 38
- **metabolism** :: `efficient` — last seen gen 33
- **lifespan** :: `mayfly` — last seen gen 33
- **lifespan** :: `normal` — last seen gen 55

## Final allele frequencies

- **color**: dominant = `crimson` (38 of 40)
- **pattern**: dominant = `solid` (35 of 40)
- **size**: dominant = `large` (28 of 40)
- **temperament**: dominant = `peaceful` (30 of 40)
- **sociability**: dominant = `pack` (39 of 40)
- **cognition**: dominant = `pattern_matcher` (35 of 40)
- **metabolism**: dominant = `voracious` (26 of 40)
- **lifespan**: dominant = `ancient` (38 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.