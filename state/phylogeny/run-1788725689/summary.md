# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 238, Carrying capacity: 40
- Total individuals ever: **1964**
- Survivors at end: **40**
- Final mean fitness: **0.7525**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `verdant` — last seen gen 55
- **pattern** :: `striped` — last seen gen 42
- **pattern** :: `spotted` — last seen gen 49
- **pattern** :: `iridescent` — last seen gen 54
- **size** :: `giant` — last seen gen 46
- **temperament** :: `curious` — last seen gen 57
- **temperament** :: `cautious` — last seen gen 53
- **temperament** :: `aggressive` — last seen gen 57
- **temperament** :: `chaotic` — last seen gen 57
- **sociability** :: `solitary` — last seen gen 49
- **sociability** :: `pair` — last seen gen 49
- **cognition** :: `deep_thinker` — last seen gen 57
- **cognition** :: `rapid_reactor` — last seen gen 41
- **cognition** :: `memory_hoarder` — last seen gen 54
- **metabolism** :: `slow_burn` — last seen gen 30
- **lifespan** :: `mayfly` — last seen gen 31
- **lifespan** :: `normal` — last seen gen 57

## Final allele frequencies

- **color**: dominant = `crimson` (25 of 40)
- **pattern**: dominant = `solid` (39 of 40)
- **size**: dominant = `tiny` (30 of 40)
- **temperament**: dominant = `peaceful` (40 of 40)
- **sociability**: dominant = `pack` (33 of 40)
- **cognition**: dominant = `pattern_matcher` (40 of 40)
- **metabolism**: dominant = `efficient` (20 of 40)
- **lifespan**: dominant = `ancient` (39 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.