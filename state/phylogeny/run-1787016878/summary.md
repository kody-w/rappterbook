# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 169, Carrying capacity: 40
- Total individuals ever: **1912**
- Survivors at end: **40**
- Final mean fitness: **0.7663**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `obsidian` — last seen gen 58
- **pattern** :: `striped` — last seen gen 39
- **size** :: `medium` — last seen gen 9
- **temperament** :: `cautious` — last seen gen 36
- **temperament** :: `aggressive` — last seen gen 36
- **temperament** :: `chaotic` — last seen gen 58
- **sociability** :: `solitary` — last seen gen 52
- **sociability** :: `pair` — last seen gen 51
- **cognition** :: `rapid_reactor` — last seen gen 39
- **cognition** :: `memory_hoarder` — last seen gen 51
- **metabolism** :: `efficient` — last seen gen 57
- **metabolism** :: `torpor` — last seen gen 23
- **lifespan** :: `mayfly` — last seen gen 37
- **lifespan** :: `normal` — last seen gen 36

## Final allele frequencies

- **color**: dominant = `crimson` (34 of 40)
- **pattern**: dominant = `solid` (31 of 40)
- **size**: dominant = `tiny` (24 of 40)
- **temperament**: dominant = `curious` (31 of 40)
- **sociability**: dominant = `pack` (35 of 40)
- **cognition**: dominant = `pattern_matcher` (25 of 40)
- **metabolism**: dominant = `voracious` (39 of 40)
- **lifespan**: dominant = `ancient` (35 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.