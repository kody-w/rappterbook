# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 220, Carrying capacity: 40
- Total individuals ever: **1703**
- Survivors at end: **40**
- Final mean fitness: **0.81**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `verdant` — last seen gen 56
- **color** :: `gold` — last seen gen 43
- **pattern** :: `solid` — last seen gen 29
- **pattern** :: `spotted` — last seen gen 52
- **size** :: `small` — last seen gen 15
- **size** :: `medium` — last seen gen 17
- **temperament** :: `curious` — last seen gen 58
- **temperament** :: `cautious` — last seen gen 34
- **temperament** :: `aggressive` — last seen gen 57
- **temperament** :: `chaotic` — last seen gen 56
- **sociability** :: `solitary` — last seen gen 17
- **sociability** :: `pair` — last seen gen 41
- **cognition** :: `deep_thinker` — last seen gen 58
- **cognition** :: `rapid_reactor` — last seen gen 27
- **cognition** :: `memory_hoarder` — last seen gen 53
- **metabolism** :: `efficient` — last seen gen 52
- **lifespan** :: `mayfly` — last seen gen 36
- **lifespan** :: `normal` — last seen gen 17
- **lifespan** :: `long` — last seen gen 30

## Final allele frequencies

- **color**: dominant = `crimson` (34 of 40)
- **pattern**: dominant = `striped` (28 of 40)
- **size**: dominant = `tiny` (37 of 40)
- **temperament**: dominant = `peaceful` (40 of 40)
- **sociability**: dominant = `pack` (38 of 40)
- **cognition**: dominant = `pattern_matcher` (40 of 40)
- **metabolism**: dominant = `voracious` (23 of 40)
- **lifespan**: dominant = `ancient` (40 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.