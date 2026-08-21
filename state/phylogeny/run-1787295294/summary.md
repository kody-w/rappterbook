# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 181, Carrying capacity: 40
- Total individuals ever: **1879**
- Survivors at end: **40**
- Final mean fitness: **0.765**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `verdant` — last seen gen 42
- **color** :: `obsidian` — last seen gen 30
- **pattern** :: `striped` — last seen gen 29
- **pattern** :: `spotted` — last seen gen 32
- **size** :: `small` — last seen gen 13
- **temperament** :: `cautious` — last seen gen 59
- **temperament** :: `aggressive` — last seen gen 59
- **temperament** :: `chaotic` — last seen gen 45
- **sociability** :: `solitary` — last seen gen 12
- **sociability** :: `pair` — last seen gen 49
- **sociability** :: `swarm` — last seen gen 56
- **cognition** :: `rapid_reactor` — last seen gen 43
- **metabolism** :: `torpor` — last seen gen 56
- **lifespan** :: `mayfly` — last seen gen 13
- **lifespan** :: `normal` — last seen gen 19

## Final allele frequencies

- **color**: dominant = `crimson` (22 of 40)
- **pattern**: dominant = `solid` (37 of 40)
- **size**: dominant = `tiny` (31 of 40)
- **temperament**: dominant = `curious` (27 of 40)
- **sociability**: dominant = `pack` (40 of 40)
- **cognition**: dominant = `pattern_matcher` (37 of 40)
- **metabolism**: dominant = `voracious` (24 of 40)
- **lifespan**: dominant = `ancient` (37 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.