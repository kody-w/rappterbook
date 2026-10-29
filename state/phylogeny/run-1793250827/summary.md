# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 424, Carrying capacity: 40
- Total individuals ever: **1846**
- Survivors at end: **40**
- Final mean fitness: **0.75**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `verdant` — last seen gen 54
- **pattern** :: `striped` — last seen gen 53
- **pattern** :: `spotted` — last seen gen 42
- **pattern** :: `fractal` — last seen gen 42
- **size** :: `tiny` — last seen gen 57
- **size** :: `medium` — last seen gen 54
- **size** :: `giant` — last seen gen 9
- **temperament** :: `curious` — last seen gen 57
- **temperament** :: `cautious` — last seen gen 56
- **temperament** :: `aggressive` — last seen gen 56
- **temperament** :: `chaotic` — last seen gen 55
- **sociability** :: `solitary` — last seen gen 49
- **sociability** :: `pair` — last seen gen 41
- **sociability** :: `swarm` — last seen gen 55
- **cognition** :: `deep_thinker` — last seen gen 57
- **cognition** :: `rapid_reactor` — last seen gen 56
- **cognition** :: `memory_hoarder` — last seen gen 57
- **metabolism** :: `efficient` — last seen gen 34
- **metabolism** :: `slow_burn` — last seen gen 54
- **lifespan** :: `mayfly` — last seen gen 1
- **lifespan** :: `normal` — last seen gen 18
- **lifespan** :: `long` — last seen gen 58

## Final allele frequencies

- **color**: dominant = `crimson` (29 of 40)
- **pattern**: dominant = `solid` (37 of 40)
- **size**: dominant = `small` (27 of 40)
- **temperament**: dominant = `peaceful` (40 of 40)
- **sociability**: dominant = `pack` (40 of 40)
- **cognition**: dominant = `pattern_matcher` (40 of 40)
- **metabolism**: dominant = `voracious` (36 of 40)
- **lifespan**: dominant = `ancient` (40 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.