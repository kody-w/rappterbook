# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 277, Carrying capacity: 40
- Total individuals ever: **1813**
- Survivors at end: **40**
- Final mean fitness: **0.7638**

## Founder bloodlines (final generation)
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%
- `scarlet-fang`:  0.0%

## Extinct alleles

- **color** :: `verdant` — last seen gen 54
- **color** :: `gold` — last seen gen 51
- **color** :: `obsidian` — last seen gen 53
- **pattern** :: `spotted` — last seen gen 44
- **pattern** :: `iridescent` — last seen gen 54
- **size** :: `medium` — last seen gen 56
- **size** :: `giant` — last seen gen 54
- **temperament** :: `cautious` — last seen gen 54
- **temperament** :: `aggressive` — last seen gen 59
- **temperament** :: `chaotic` — last seen gen 59
- **sociability** :: `solitary` — last seen gen 54
- **sociability** :: `pair` — last seen gen 53
- **cognition** :: `rapid_reactor` — last seen gen 53
- **cognition** :: `memory_hoarder` — last seen gen 54
- **lifespan** :: `mayfly` — last seen gen 12
- **lifespan** :: `normal` — last seen gen 59

## Final allele frequencies

- **color**: dominant = `crimson` (38 of 40)
- **pattern**: dominant = `solid` (30 of 40)
- **size**: dominant = `large` (28 of 40)
- **temperament**: dominant = `curious` (27 of 40)
- **sociability**: dominant = `pack` (23 of 40)
- **cognition**: dominant = `pattern_matcher` (39 of 40)
- **metabolism**: dominant = `voracious` (33 of 40)
- **lifespan**: dominant = `ancient` (36 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.