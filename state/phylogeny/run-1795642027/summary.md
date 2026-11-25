# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 496, Carrying capacity: 40
- Total individuals ever: **1824**
- Survivors at end: **40**
- Final mean fitness: **0.7537**

## Founder bloodlines (final generation)
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%
- `scarlet-fang`:  0.0%

## Extinct alleles

- **color** :: `verdant` — last seen gen 57
- **color** :: `obsidian` — last seen gen 56
- **pattern** :: `striped` — last seen gen 45
- **pattern** :: `fractal` — last seen gen 53
- **size** :: `small` — last seen gen 41
- **temperament** :: `curious` — last seen gen 56
- **temperament** :: `cautious` — last seen gen 54
- **temperament** :: `aggressive` — last seen gen 56
- **temperament** :: `chaotic` — last seen gen 55
- **sociability** :: `solitary` — last seen gen 52
- **sociability** :: `pair` — last seen gen 56
- **cognition** :: `deep_thinker` — last seen gen 56
- **cognition** :: `rapid_reactor` — last seen gen 46
- **cognition** :: `memory_hoarder` — last seen gen 56
- **metabolism** :: `torpor` — last seen gen 23
- **lifespan** :: `mayfly` — last seen gen 38
- **lifespan** :: `normal` — last seen gen 57
- **lifespan** :: `long` — last seen gen 37

## Final allele frequencies

- **color**: dominant = `azure` (22 of 40)
- **pattern**: dominant = `solid` (29 of 40)
- **size**: dominant = `large` (33 of 40)
- **temperament**: dominant = `peaceful` (40 of 40)
- **sociability**: dominant = `pack` (34 of 40)
- **cognition**: dominant = `pattern_matcher` (40 of 40)
- **metabolism**: dominant = `voracious` (26 of 40)
- **lifespan**: dominant = `ancient` (40 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.