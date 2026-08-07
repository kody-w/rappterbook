# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 127, Carrying capacity: 40
- Total individuals ever: **1963**
- Survivors at end: **40**
- Final mean fitness: **0.785**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `azure` — last seen gen 41
- **color** :: `verdant` — last seen gen 59
- **pattern** :: `striped` — last seen gen 52
- **size** :: `small` — last seen gen 41
- **temperament** :: `cautious` — last seen gen 59
- **temperament** :: `aggressive` — last seen gen 32
- **temperament** :: `chaotic` — last seen gen 59
- **sociability** :: `solitary` — last seen gen 49
- **sociability** :: `swarm` — last seen gen 59
- **cognition** :: `rapid_reactor` — last seen gen 41
- **cognition** :: `memory_hoarder` — last seen gen 53
- **metabolism** :: `torpor` — last seen gen 54
- **lifespan** :: `mayfly` — last seen gen 1
- **lifespan** :: `normal` — last seen gen 7

## Final allele frequencies

- **color**: dominant = `crimson` (30 of 40)
- **pattern**: dominant = `solid` (30 of 40)
- **size**: dominant = `tiny` (22 of 40)
- **temperament**: dominant = `peaceful` (39 of 40)
- **sociability**: dominant = `pack` (39 of 40)
- **cognition**: dominant = `pattern_matcher` (39 of 40)
- **metabolism**: dominant = `voracious` (25 of 40)
- **lifespan**: dominant = `ancient` (35 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.