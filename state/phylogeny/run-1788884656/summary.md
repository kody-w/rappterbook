# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 244, Carrying capacity: 40
- Total individuals ever: **1914**
- Survivors at end: **40**
- Final mean fitness: **0.76**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `azure` — last seen gen 50
- **color** :: `obsidian` — last seen gen 18
- **pattern** :: `iridescent` — last seen gen 50
- **pattern** :: `fractal` — last seen gen 33
- **size** :: `small` — last seen gen 54
- **size** :: `large` — last seen gen 55
- **size** :: `giant` — last seen gen 33
- **temperament** :: `cautious` — last seen gen 59
- **temperament** :: `aggressive` — last seen gen 37
- **temperament** :: `chaotic` — last seen gen 59
- **sociability** :: `solitary` — last seen gen 55
- **cognition** :: `rapid_reactor` — last seen gen 53
- **metabolism** :: `efficient` — last seen gen 37
- **lifespan** :: `mayfly` — last seen gen 35
- **lifespan** :: `normal` — last seen gen 15

## Final allele frequencies

- **color**: dominant = `crimson` (37 of 40)
- **pattern**: dominant = `solid` (31 of 40)
- **size**: dominant = `tiny` (35 of 40)
- **temperament**: dominant = `curious` (28 of 40)
- **sociability**: dominant = `pack` (35 of 40)
- **cognition**: dominant = `pattern_matcher` (37 of 40)
- **metabolism**: dominant = `voracious` (37 of 40)
- **lifespan**: dominant = `ancient` (39 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.