# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 124, Carrying capacity: 40
- Total individuals ever: **1862**
- Survivors at end: **40**
- Final mean fitness: **0.7562**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `gold` — last seen gen 58
- **size** :: `tiny` — last seen gen 27
- **size** :: `medium` — last seen gen 16
- **size** :: `giant` — last seen gen 53
- **temperament** :: `cautious` — last seen gen 56
- **temperament** :: `aggressive` — last seen gen 37
- **temperament** :: `chaotic` — last seen gen 59
- **sociability** :: `solitary` — last seen gen 50
- **sociability** :: `pair` — last seen gen 11
- **cognition** :: `rapid_reactor` — last seen gen 37
- **cognition** :: `memory_hoarder` — last seen gen 54
- **metabolism** :: `efficient` — last seen gen 56
- **lifespan** :: `mayfly` — last seen gen 16
- **lifespan** :: `normal` — last seen gen 59

## Final allele frequencies

- **color**: dominant = `crimson` (36 of 40)
- **pattern**: dominant = `solid` (22 of 40)
- **size**: dominant = `large` (20 of 40)
- **temperament**: dominant = `peaceful` (27 of 40)
- **sociability**: dominant = `pack` (34 of 40)
- **cognition**: dominant = `pattern_matcher` (38 of 40)
- **metabolism**: dominant = `voracious` (38 of 40)
- **lifespan**: dominant = `ancient` (39 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.