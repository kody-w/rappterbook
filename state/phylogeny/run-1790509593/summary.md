# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 316, Carrying capacity: 40
- Total individuals ever: **1844**
- Survivors at end: **40**
- Final mean fitness: **0.7588**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `gold` — last seen gen 59
- **color** :: `obsidian` — last seen gen 31
- **pattern** :: `iridescent` — last seen gen 57
- **size** :: `tiny` — last seen gen 26
- **temperament** :: `cautious` — last seen gen 35
- **temperament** :: `aggressive` — last seen gen 59
- **temperament** :: `chaotic` — last seen gen 59
- **sociability** :: `solitary` — last seen gen 50
- **sociability** :: `pair` — last seen gen 50
- **sociability** :: `swarm` — last seen gen 57
- **cognition** :: `rapid_reactor` — last seen gen 44
- **metabolism** :: `torpor` — last seen gen 57
- **lifespan** :: `mayfly` — last seen gen 36
- **lifespan** :: `normal` — last seen gen 57

## Final allele frequencies

- **color**: dominant = `crimson` (33 of 40)
- **pattern**: dominant = `solid` (30 of 40)
- **size**: dominant = `large` (30 of 40)
- **temperament**: dominant = `curious` (26 of 40)
- **sociability**: dominant = `pack` (40 of 40)
- **cognition**: dominant = `pattern_matcher` (35 of 40)
- **metabolism**: dominant = `voracious` (37 of 40)
- **lifespan**: dominant = `ancient` (38 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.