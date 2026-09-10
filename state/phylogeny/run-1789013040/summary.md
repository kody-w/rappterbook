# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 250, Carrying capacity: 40
- Total individuals ever: **1703**
- Survivors at end: **40**
- Final mean fitness: **0.755**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `verdant` — last seen gen 50
- **color** :: `gold` — last seen gen 58
- **pattern** :: `spotted` — last seen gen 57
- **size** :: `tiny` — last seen gen 58
- **size** :: `giant` — last seen gen 39
- **temperament** :: `cautious` — last seen gen 59
- **temperament** :: `aggressive` — last seen gen 50
- **temperament** :: `chaotic` — last seen gen 40
- **sociability** :: `pair` — last seen gen 58
- **cognition** :: `rapid_reactor` — last seen gen 58
- **cognition** :: `memory_hoarder` — last seen gen 58
- **metabolism** :: `efficient` — last seen gen 33
- **metabolism** :: `slow_burn` — last seen gen 56
- **metabolism** :: `torpor` — last seen gen 57
- **lifespan** :: `mayfly` — last seen gen 36
- **lifespan** :: `normal` — last seen gen 59

## Final allele frequencies

- **color**: dominant = `azure` (25 of 40)
- **pattern**: dominant = `solid` (37 of 40)
- **size**: dominant = `medium` (33 of 40)
- **temperament**: dominant = `curious` (37 of 40)
- **sociability**: dominant = `pack` (35 of 40)
- **cognition**: dominant = `pattern_matcher` (31 of 40)
- **metabolism**: dominant = `voracious` (40 of 40)
- **lifespan**: dominant = `ancient` (38 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.