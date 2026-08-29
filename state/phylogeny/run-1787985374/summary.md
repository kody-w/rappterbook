# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 205, Carrying capacity: 40
- Total individuals ever: **1796**
- Survivors at end: **40**
- Final mean fitness: **0.7625**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `verdant` — last seen gen 57
- **color** :: `gold` — last seen gen 52
- **color** :: `obsidian` — last seen gen 53
- **pattern** :: `iridescent` — last seen gen 57
- **size** :: `small` — last seen gen 58
- **size** :: `medium` — last seen gen 56
- **temperament** :: `cautious` — last seen gen 59
- **temperament** :: `aggressive` — last seen gen 57
- **temperament** :: `chaotic` — last seen gen 53
- **sociability** :: `solitary` — last seen gen 13
- **sociability** :: `pair` — last seen gen 49
- **cognition** :: `rapid_reactor` — last seen gen 21
- **metabolism** :: `slow_burn` — last seen gen 49
- **metabolism** :: `torpor` — last seen gen 13
- **lifespan** :: `mayfly` — last seen gen 36
- **lifespan** :: `normal` — last seen gen 17

## Final allele frequencies

- **color**: dominant = `crimson` (38 of 40)
- **pattern**: dominant = `striped` (30 of 40)
- **size**: dominant = `tiny` (22 of 40)
- **temperament**: dominant = `peaceful` (36 of 40)
- **sociability**: dominant = `pack` (36 of 40)
- **cognition**: dominant = `pattern_matcher` (38 of 40)
- **metabolism**: dominant = `voracious` (32 of 40)
- **lifespan**: dominant = `ancient` (35 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.