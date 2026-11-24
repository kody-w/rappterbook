# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 493, Carrying capacity: 40
- Total individuals ever: **1863**
- Survivors at end: **40**
- Final mean fitness: **0.7537**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `azure` — last seen gen 45
- **pattern** :: `striped` — last seen gen 57
- **pattern** :: `fractal` — last seen gen 24
- **size** :: `small` — last seen gen 22
- **temperament** :: `cautious` — last seen gen 45
- **temperament** :: `aggressive` — last seen gen 55
- **temperament** :: `chaotic` — last seen gen 56
- **sociability** :: `solitary` — last seen gen 50
- **sociability** :: `pair` — last seen gen 56
- **cognition** :: `rapid_reactor` — last seen gen 57
- **metabolism** :: `torpor` — last seen gen 56
- **lifespan** :: `mayfly` — last seen gen 8
- **lifespan** :: `normal` — last seen gen 51
- **lifespan** :: `long` — last seen gen 57

## Final allele frequencies

- **color**: dominant = `crimson` (35 of 40)
- **pattern**: dominant = `solid` (34 of 40)
- **size**: dominant = `tiny` (20 of 40)
- **temperament**: dominant = `curious` (37 of 40)
- **sociability**: dominant = `pack` (25 of 40)
- **cognition**: dominant = `pattern_matcher` (37 of 40)
- **metabolism**: dominant = `voracious` (38 of 40)
- **lifespan**: dominant = `ancient` (40 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.