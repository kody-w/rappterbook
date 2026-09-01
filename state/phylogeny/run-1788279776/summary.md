# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 217, Carrying capacity: 40
- Total individuals ever: **1980**
- Survivors at end: **40**
- Final mean fitness: **0.75**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`:  0.0%

## Extinct alleles

- **color** :: `azure` — last seen gen 32
- **color** :: `verdant` — last seen gen 7
- **color** :: `obsidian` — last seen gen 54
- **pattern** :: `striped` — last seen gen 56
- **pattern** :: `fractal` — last seen gen 51
- **size** :: `medium` — last seen gen 7
- **temperament** :: `cautious` — last seen gen 51
- **temperament** :: `aggressive` — last seen gen 12
- **temperament** :: `chaotic` — last seen gen 59
- **sociability** :: `pair` — last seen gen 27
- **cognition** :: `rapid_reactor` — last seen gen 53
- **cognition** :: `memory_hoarder` — last seen gen 55
- **metabolism** :: `efficient` — last seen gen 57
- **metabolism** :: `slow_burn` — last seen gen 58
- **lifespan** :: `mayfly` — last seen gen 33
- **lifespan** :: `normal` — last seen gen 55
- **lifespan** :: `long` — last seen gen 55

## Final allele frequencies

- **color**: dominant = `crimson` (36 of 40)
- **pattern**: dominant = `solid` (29 of 40)
- **size**: dominant = `tiny` (22 of 40)
- **temperament**: dominant = `curious` (23 of 40)
- **sociability**: dominant = `pack` (31 of 40)
- **cognition**: dominant = `pattern_matcher` (39 of 40)
- **metabolism**: dominant = `voracious` (38 of 40)
- **lifespan**: dominant = `ancient` (40 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.