# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 253, Carrying capacity: 40
- Total individuals ever: **1782**
- Survivors at end: **40**
- Final mean fitness: **0.7537**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **pattern** :: `striped` — last seen gen 56
- **pattern** :: `spotted` — last seen gen 40
- **pattern** :: `fractal` — last seen gen 2
- **temperament** :: `curious` — last seen gen 56
- **temperament** :: `cautious` — last seen gen 37
- **temperament** :: `aggressive` — last seen gen 55
- **temperament** :: `chaotic` — last seen gen 52
- **sociability** :: `solitary` — last seen gen 49
- **sociability** :: `pair` — last seen gen 49
- **sociability** :: `swarm` — last seen gen 45
- **cognition** :: `deep_thinker` — last seen gen 56
- **cognition** :: `rapid_reactor` — last seen gen 38
- **cognition** :: `memory_hoarder` — last seen gen 56
- **lifespan** :: `mayfly` — last seen gen 39
- **lifespan** :: `normal` — last seen gen 53
- **lifespan** :: `long` — last seen gen 41

## Final allele frequencies

- **color**: dominant = `azure` (34 of 40)
- **pattern**: dominant = `solid` (34 of 40)
- **size**: dominant = `tiny` (23 of 40)
- **temperament**: dominant = `peaceful` (40 of 40)
- **sociability**: dominant = `pack` (40 of 40)
- **cognition**: dominant = `pattern_matcher` (40 of 40)
- **metabolism**: dominant = `voracious` (27 of 40)
- **lifespan**: dominant = `ancient` (40 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.