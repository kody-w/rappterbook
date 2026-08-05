# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 121, Carrying capacity: 40
- Total individuals ever: **1831**
- Survivors at end: **40**
- Final mean fitness: **0.7675**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `azure` — last seen gen 56
- **color** :: `verdant` — last seen gen 21
- **color** :: `gold` — last seen gen 40
- **color** :: `obsidian` — last seen gen 44
- **pattern** :: `fractal` — last seen gen 55
- **temperament** :: `cautious` — last seen gen 56
- **temperament** :: `aggressive` — last seen gen 59
- **temperament** :: `chaotic` — last seen gen 58
- **sociability** :: `solitary` — last seen gen 55
- **sociability** :: `pair` — last seen gen 54
- **cognition** :: `deep_thinker` — last seen gen 58
- **lifespan** :: `mayfly` — last seen gen 32
- **lifespan** :: `normal` — last seen gen 7

## Final allele frequencies

- **color**: dominant = `crimson` (40 of 40)
- **pattern**: dominant = `solid` (33 of 40)
- **size**: dominant = `medium` (17 of 40)
- **temperament**: dominant = `peaceful` (32 of 40)
- **sociability**: dominant = `pack` (33 of 40)
- **cognition**: dominant = `pattern_matcher` (33 of 40)
- **metabolism**: dominant = `voracious` (26 of 40)
- **lifespan**: dominant = `ancient` (39 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.