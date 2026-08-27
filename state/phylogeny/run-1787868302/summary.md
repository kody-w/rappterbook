# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 202, Carrying capacity: 40
- Total individuals ever: **1736**
- Survivors at end: **40**
- Final mean fitness: **0.755**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `verdant` — last seen gen 57
- **color** :: `gold` — last seen gen 42
- **color** :: `obsidian` — last seen gen 55
- **pattern** :: `striped` — last seen gen 54
- **pattern** :: `spotted` — last seen gen 53
- **pattern** :: `iridescent` — last seen gen 55
- **size** :: `small` — last seen gen 25
- **size** :: `medium` — last seen gen 26
- **temperament** :: `aggressive` — last seen gen 59
- **temperament** :: `chaotic` — last seen gen 59
- **sociability** :: `solitary` — last seen gen 56
- **sociability** :: `pair` — last seen gen 42
- **cognition** :: `rapid_reactor` — last seen gen 45
- **cognition** :: `memory_hoarder` — last seen gen 56
- **lifespan** :: `mayfly` — last seen gen 31
- **lifespan** :: `normal` — last seen gen 53

## Final allele frequencies

- **color**: dominant = `crimson` (39 of 40)
- **pattern**: dominant = `solid` (39 of 40)
- **size**: dominant = `large` (37 of 40)
- **temperament**: dominant = `curious` (35 of 40)
- **sociability**: dominant = `pack` (25 of 40)
- **cognition**: dominant = `pattern_matcher` (39 of 40)
- **metabolism**: dominant = `voracious` (36 of 40)
- **lifespan**: dominant = `ancient` (38 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.