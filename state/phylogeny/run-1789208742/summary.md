# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 259, Carrying capacity: 40
- Total individuals ever: **1808**
- Survivors at end: **40**
- Final mean fitness: **0.75**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `verdant` — last seen gen 33
- **color** :: `gold` — last seen gen 57
- **temperament** :: `cautious` — last seen gen 57
- **temperament** :: `aggressive` — last seen gen 29
- **temperament** :: `chaotic` — last seen gen 46
- **sociability** :: `solitary` — last seen gen 57
- **sociability** :: `pair` — last seen gen 41
- **cognition** :: `rapid_reactor` — last seen gen 56
- **cognition** :: `memory_hoarder` — last seen gen 57
- **metabolism** :: `efficient` — last seen gen 29
- **metabolism** :: `slow_burn` — last seen gen 23
- **metabolism** :: `torpor` — last seen gen 57
- **lifespan** :: `mayfly` — last seen gen 10
- **lifespan** :: `normal` — last seen gen 12
- **lifespan** :: `long` — last seen gen 29

## Final allele frequencies

- **color**: dominant = `crimson` (38 of 40)
- **pattern**: dominant = `spotted` (31 of 40)
- **size**: dominant = `tiny` (31 of 40)
- **temperament**: dominant = `curious` (37 of 40)
- **sociability**: dominant = `pack` (32 of 40)
- **cognition**: dominant = `pattern_matcher` (39 of 40)
- **metabolism**: dominant = `voracious` (40 of 40)
- **lifespan**: dominant = `ancient` (40 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.