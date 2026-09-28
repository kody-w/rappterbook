# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 319, Carrying capacity: 40
- Total individuals ever: **1775**
- Survivors at end: **40**
- Final mean fitness: **0.7575**

## Founder bloodlines (final generation)
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%
- `scarlet-fang`:  0.0%

## Extinct alleles

- **color** :: `verdant` — last seen gen 15
- **color** :: `obsidian` — last seen gen 56
- **pattern** :: `iridescent` — last seen gen 46
- **pattern** :: `fractal` — last seen gen 55
- **size** :: `giant` — last seen gen 58
- **temperament** :: `cautious` — last seen gen 29
- **temperament** :: `aggressive` — last seen gen 24
- **temperament** :: `chaotic` — last seen gen 59
- **sociability** :: `solitary` — last seen gen 49
- **sociability** :: `pair` — last seen gen 15
- **cognition** :: `rapid_reactor` — last seen gen 39
- **metabolism** :: `torpor` — last seen gen 8
- **lifespan** :: `mayfly` — last seen gen 19
- **lifespan** :: `normal` — last seen gen 56
- **lifespan** :: `long` — last seen gen 29

## Final allele frequencies

- **color**: dominant = `crimson` (28 of 40)
- **pattern**: dominant = `solid` (35 of 40)
- **size**: dominant = `tiny` (33 of 40)
- **temperament**: dominant = `curious` (30 of 40)
- **sociability**: dominant = `pack` (34 of 40)
- **cognition**: dominant = `pattern_matcher` (34 of 40)
- **metabolism**: dominant = `voracious` (31 of 40)
- **lifespan**: dominant = `ancient` (40 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.