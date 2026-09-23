# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 301, Carrying capacity: 40
- Total individuals ever: **1795**
- Survivors at end: **40**
- Final mean fitness: **0.75**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `verdant` — last seen gen 14
- **pattern** :: `striped` — last seen gen 57
- **pattern** :: `spotted` — last seen gen 41
- **pattern** :: `iridescent` — last seen gen 57
- **size** :: `small` — last seen gen 12
- **temperament** :: `cautious` — last seen gen 33
- **temperament** :: `aggressive` — last seen gen 56
- **temperament** :: `chaotic` — last seen gen 57
- **sociability** :: `solitary` — last seen gen 12
- **sociability** :: `pair` — last seen gen 50
- **cognition** :: `memory_hoarder` — last seen gen 14
- **metabolism** :: `slow_burn` — last seen gen 15
- **lifespan** :: `mayfly` — last seen gen 11
- **lifespan** :: `normal` — last seen gen 50
- **lifespan** :: `long` — last seen gen 57

## Final allele frequencies

- **color**: dominant = `crimson` (34 of 40)
- **pattern**: dominant = `solid` (38 of 40)
- **size**: dominant = `tiny` (22 of 40)
- **temperament**: dominant = `peaceful` (35 of 40)
- **sociability**: dominant = `pack` (37 of 40)
- **cognition**: dominant = `pattern_matcher` (21 of 40)
- **metabolism**: dominant = `voracious` (33 of 40)
- **lifespan**: dominant = `ancient` (40 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.