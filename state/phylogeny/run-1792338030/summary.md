# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 385, Carrying capacity: 40
- Total individuals ever: **2051**
- Survivors at end: **40**
- Final mean fitness: **0.7562**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`:  0.0%
- `gold-storm`:  0.0%

## Extinct alleles

- **color** :: `azure` — last seen gen 44
- **pattern** :: `iridescent` — last seen gen 44
- **pattern** :: `fractal` — last seen gen 25
- **size** :: `medium` — last seen gen 54
- **temperament** :: `cautious` — last seen gen 33
- **temperament** :: `aggressive` — last seen gen 53
- **temperament** :: `chaotic` — last seen gen 59
- **sociability** :: `solitary` — last seen gen 49
- **sociability** :: `pair` — last seen gen 49
- **cognition** :: `deep_thinker` — last seen gen 55
- **cognition** :: `rapid_reactor` — last seen gen 28
- **cognition** :: `memory_hoarder` — last seen gen 58
- **lifespan** :: `mayfly` — last seen gen 30
- **lifespan** :: `normal` — last seen gen 56

## Final allele frequencies

- **color**: dominant = `crimson` (29 of 40)
- **pattern**: dominant = `solid` (20 of 40)
- **size**: dominant = `tiny` (25 of 40)
- **temperament**: dominant = `curious` (26 of 40)
- **sociability**: dominant = `pack` (39 of 40)
- **cognition**: dominant = `pattern_matcher` (40 of 40)
- **metabolism**: dominant = `voracious` (30 of 40)
- **lifespan**: dominant = `ancient` (39 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.