# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 229, Carrying capacity: 40
- Total individuals ever: **1999**
- Survivors at end: **40**
- Final mean fitness: **0.765**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `crimson` — last seen gen 35
- **pattern** :: `spotted` — last seen gen 55
- **pattern** :: `iridescent` — last seen gen 43
- **pattern** :: `fractal` — last seen gen 44
- **size** :: `large` — last seen gen 52
- **size** :: `giant` — last seen gen 8
- **temperament** :: `cautious` — last seen gen 56
- **temperament** :: `aggressive` — last seen gen 14
- **temperament** :: `chaotic` — last seen gen 51
- **metabolism** :: `torpor` — last seen gen 23
- **lifespan** :: `mayfly` — last seen gen 1
- **lifespan** :: `normal` — last seen gen 35
- **lifespan** :: `long` — last seen gen 19

## Final allele frequencies

- **color**: dominant = `azure` (32 of 40)
- **pattern**: dominant = `solid` (27 of 40)
- **size**: dominant = `tiny` (36 of 40)
- **temperament**: dominant = `peaceful` (28 of 40)
- **sociability**: dominant = `pack` (30 of 40)
- **cognition**: dominant = `pattern_matcher` (25 of 40)
- **metabolism**: dominant = `voracious` (31 of 40)
- **lifespan**: dominant = `ancient` (40 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.