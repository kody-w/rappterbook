# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 460, Carrying capacity: 40
- Total individuals ever: **1941**
- Survivors at end: **40**
- Final mean fitness: **0.7575**

## Founder bloodlines (final generation)
- `azure-mind`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%
- `scarlet-fang`:  0.0%
- `verdant-vow`:  0.0%

## Extinct alleles

- **color** :: `verdant` — last seen gen 51
- **pattern** :: `striped` — last seen gen 29
- **size** :: `giant` — last seen gen 57
- **temperament** :: `cautious` — last seen gen 54
- **temperament** :: `aggressive` — last seen gen 59
- **temperament** :: `chaotic` — last seen gen 54
- **sociability** :: `solitary` — last seen gen 40
- **sociability** :: `pair` — last seen gen 24
- **cognition** :: `rapid_reactor` — last seen gen 40
- **cognition** :: `memory_hoarder` — last seen gen 54
- **metabolism** :: `efficient` — last seen gen 28
- **metabolism** :: `torpor` — last seen gen 25
- **lifespan** :: `mayfly` — last seen gen 31
- **lifespan** :: `normal` — last seen gen 54
- **lifespan** :: `long` — last seen gen 35

## Final allele frequencies

- **color**: dominant = `crimson` (32 of 40)
- **pattern**: dominant = `solid` (33 of 40)
- **size**: dominant = `large` (22 of 40)
- **temperament**: dominant = `curious` (30 of 40)
- **sociability**: dominant = `pack` (39 of 40)
- **cognition**: dominant = `pattern_matcher` (38 of 40)
- **metabolism**: dominant = `voracious` (38 of 40)
- **lifespan**: dominant = `ancient` (40 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.