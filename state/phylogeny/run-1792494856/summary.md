# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 391, Carrying capacity: 40
- Total individuals ever: **1787**
- Survivors at end: **40**
- Final mean fitness: **0.75**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `gold` — last seen gen 29
- **pattern** :: `iridescent` — last seen gen 48
- **size** :: `tiny` — last seen gen 56
- **size** :: `medium` — last seen gen 34
- **temperament** :: `cautious` — last seen gen 35
- **temperament** :: `aggressive` — last seen gen 59
- **sociability** :: `solitary` — last seen gen 51
- **sociability** :: `pair` — last seen gen 51
- **cognition** :: `rapid_reactor` — last seen gen 56
- **cognition** :: `memory_hoarder` — last seen gen 56
- **metabolism** :: `torpor` — last seen gen 57
- **lifespan** :: `mayfly` — last seen gen 8
- **lifespan** :: `normal` — last seen gen 57
- **lifespan** :: `long` — last seen gen 37

## Final allele frequencies

- **color**: dominant = `crimson` (31 of 40)
- **pattern**: dominant = `solid` (29 of 40)
- **size**: dominant = `small` (32 of 40)
- **temperament**: dominant = `curious` (31 of 40)
- **sociability**: dominant = `pack` (25 of 40)
- **cognition**: dominant = `pattern_matcher` (36 of 40)
- **metabolism**: dominant = `voracious` (29 of 40)
- **lifespan**: dominant = `ancient` (40 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.