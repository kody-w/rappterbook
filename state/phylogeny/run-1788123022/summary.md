# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 211, Carrying capacity: 40
- Total individuals ever: **1688**
- Survivors at end: **40**
- Final mean fitness: **0.7612**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `verdant` — last seen gen 53
- **color** :: `gold` — last seen gen 54
- **color** :: `obsidian` — last seen gen 17
- **pattern** :: `iridescent` — last seen gen 48
- **pattern** :: `fractal` — last seen gen 28
- **size** :: `small` — last seen gen 49
- **size** :: `medium` — last seen gen 43
- **temperament** :: `cautious` — last seen gen 59
- **temperament** :: `aggressive` — last seen gen 24
- **temperament** :: `peaceful` — last seen gen 11
- **temperament** :: `chaotic` — last seen gen 2
- **sociability** :: `solitary` — last seen gen 49
- **sociability** :: `pair` — last seen gen 14
- **cognition** :: `deep_thinker` — last seen gen 49
- **cognition** :: `rapid_reactor` — last seen gen 43
- **cognition** :: `memory_hoarder` — last seen gen 31
- **metabolism** :: `efficient` — last seen gen 29
- **metabolism** :: `torpor` — last seen gen 28
- **lifespan** :: `mayfly` — last seen gen 12
- **lifespan** :: `normal` — last seen gen 15
- **lifespan** :: `long` — last seen gen 50

## Final allele frequencies

- **color**: dominant = `crimson` (35 of 40)
- **pattern**: dominant = `solid` (31 of 40)
- **size**: dominant = `tiny` (26 of 40)
- **temperament**: dominant = `curious` (40 of 40)
- **sociability**: dominant = `pack` (35 of 40)
- **cognition**: dominant = `pattern_matcher` (40 of 40)
- **metabolism**: dominant = `voracious` (37 of 40)
- **lifespan**: dominant = `ancient` (40 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.