# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 262, Carrying capacity: 40
- Total individuals ever: **1926**
- Survivors at end: **40**
- Final mean fitness: **0.75**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `verdant` — last seen gen 43
- **pattern** :: `iridescent` — last seen gen 50
- **temperament** :: `cautious` — last seen gen 53
- **temperament** :: `aggressive` — last seen gen 52
- **temperament** :: `chaotic` — last seen gen 50
- **sociability** :: `solitary` — last seen gen 58
- **sociability** :: `pair` — last seen gen 45
- **cognition** :: `rapid_reactor` — last seen gen 45
- **cognition** :: `memory_hoarder` — last seen gen 55
- **metabolism** :: `slow_burn` — last seen gen 6
- **lifespan** :: `mayfly` — last seen gen 32
- **lifespan** :: `normal` — last seen gen 52
- **lifespan** :: `long` — last seen gen 31

## Final allele frequencies

- **color**: dominant = `crimson` (37 of 40)
- **pattern**: dominant = `solid` (31 of 40)
- **size**: dominant = `tiny` (16 of 40)
- **temperament**: dominant = `peaceful` (33 of 40)
- **sociability**: dominant = `pack` (32 of 40)
- **cognition**: dominant = `pattern_matcher` (34 of 40)
- **metabolism**: dominant = `voracious` (36 of 40)
- **lifespan**: dominant = `ancient` (40 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.