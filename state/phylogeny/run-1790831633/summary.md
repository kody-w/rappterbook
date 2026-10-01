# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 328, Carrying capacity: 40
- Total individuals ever: **1907**
- Survivors at end: **40**
- Final mean fitness: **0.77**

## Founder bloodlines (final generation)
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%
- `scarlet-fang`:  0.0%

## Extinct alleles

- **color** :: `verdant` — last seen gen 53
- **size** :: `giant` — last seen gen 58
- **temperament** :: `cautious` — last seen gen 34
- **temperament** :: `aggressive` — last seen gen 59
- **temperament** :: `chaotic` — last seen gen 20
- **sociability** :: `solitary` — last seen gen 53
- **sociability** :: `pair` — last seen gen 50
- **cognition** :: `rapid_reactor` — last seen gen 45
- **metabolism** :: `efficient` — last seen gen 29
- **lifespan** :: `mayfly` — last seen gen 35
- **lifespan** :: `normal` — last seen gen 16

## Final allele frequencies

- **color**: dominant = `crimson` (21 of 40)
- **pattern**: dominant = `solid` (20 of 40)
- **size**: dominant = `tiny` (37 of 40)
- **temperament**: dominant = `curious` (34 of 40)
- **sociability**: dominant = `pack` (39 of 40)
- **cognition**: dominant = `pattern_matcher` (38 of 40)
- **metabolism**: dominant = `voracious` (35 of 40)
- **lifespan**: dominant = `ancient` (38 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.