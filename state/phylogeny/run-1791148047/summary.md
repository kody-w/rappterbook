# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 340, Carrying capacity: 40
- Total individuals ever: **1883**
- Survivors at end: **40**
- Final mean fitness: **0.7525**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **pattern** :: `iridescent` — last seen gen 55
- **pattern** :: `fractal` — last seen gen 27
- **size** :: `tiny` — last seen gen 23
- **temperament** :: `cautious` — last seen gen 37
- **temperament** :: `aggressive` — last seen gen 37
- **temperament** :: `chaotic` — last seen gen 59
- **sociability** :: `solitary` — last seen gen 55
- **sociability** :: `pair` — last seen gen 51
- **sociability** :: `swarm` — last seen gen 55
- **cognition** :: `rapid_reactor` — last seen gen 55
- **cognition** :: `memory_hoarder` — last seen gen 55
- **metabolism** :: `slow_burn` — last seen gen 25
- **lifespan** :: `mayfly` — last seen gen 38
- **lifespan** :: `normal` — last seen gen 16

## Final allele frequencies

- **color**: dominant = `crimson` (30 of 40)
- **pattern**: dominant = `solid` (36 of 40)
- **size**: dominant = `large` (21 of 40)
- **temperament**: dominant = `curious` (30 of 40)
- **sociability**: dominant = `pack` (40 of 40)
- **cognition**: dominant = `pattern_matcher` (38 of 40)
- **metabolism**: dominant = `voracious` (37 of 40)
- **lifespan**: dominant = `ancient` (39 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.