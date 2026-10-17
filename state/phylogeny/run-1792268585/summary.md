# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 382, Carrying capacity: 40
- Total individuals ever: **1833**
- Survivors at end: **40**
- Final mean fitness: **0.75**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `azure` — last seen gen 54
- **color** :: `verdant` — last seen gen 56
- **color** :: `gold` — last seen gen 20
- **color** :: `obsidian` — last seen gen 35
- **pattern** :: `iridescent` — last seen gen 57
- **pattern** :: `fractal` — last seen gen 58
- **size** :: `small` — last seen gen 30
- **size** :: `medium` — last seen gen 12
- **size** :: `giant` — last seen gen 26
- **temperament** :: `cautious` — last seen gen 50
- **temperament** :: `aggressive` — last seen gen 15
- **temperament** :: `chaotic` — last seen gen 59
- **sociability** :: `solitary` — last seen gen 8
- **sociability** :: `pair` — last seen gen 54
- **cognition** :: `deep_thinker` — last seen gen 58
- **cognition** :: `rapid_reactor` — last seen gen 35
- **metabolism** :: `efficient` — last seen gen 50
- **metabolism** :: `slow_burn` — last seen gen 50
- **lifespan** :: `mayfly` — last seen gen 37
- **lifespan** :: `normal` — last seen gen 9
- **lifespan** :: `long` — last seen gen 36

## Final allele frequencies

- **color**: dominant = `crimson` (40 of 40)
- **pattern**: dominant = `solid` (36 of 40)
- **size**: dominant = `large` (37 of 40)
- **temperament**: dominant = `peaceful` (26 of 40)
- **sociability**: dominant = `pack` (35 of 40)
- **cognition**: dominant = `pattern_matcher` (39 of 40)
- **metabolism**: dominant = `voracious` (38 of 40)
- **lifespan**: dominant = `ancient` (40 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.