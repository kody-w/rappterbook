# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 199, Carrying capacity: 40
- Total individuals ever: **1742**
- Survivors at end: **40**
- Final mean fitness: **0.75**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `gold` — last seen gen 53
- **pattern** :: `spotted` — last seen gen 54
- **pattern** :: `iridescent` — last seen gen 24
- **pattern** :: `fractal` — last seen gen 13
- **size** :: `small` — last seen gen 8
- **size** :: `giant` — last seen gen 53
- **temperament** :: `cautious` — last seen gen 59
- **temperament** :: `aggressive` — last seen gen 51
- **temperament** :: `chaotic` — last seen gen 59
- **sociability** :: `solitary` — last seen gen 51
- **sociability** :: `pair` — last seen gen 55
- **cognition** :: `deep_thinker` — last seen gen 55
- **cognition** :: `rapid_reactor` — last seen gen 40
- **cognition** :: `memory_hoarder` — last seen gen 52
- **metabolism** :: `slow_burn` — last seen gen 25
- **lifespan** :: `mayfly` — last seen gen 38
- **lifespan** :: `normal` — last seen gen 55
- **lifespan** :: `long` — last seen gen 55

## Final allele frequencies

- **color**: dominant = `crimson` (33 of 40)
- **pattern**: dominant = `solid` (39 of 40)
- **size**: dominant = `tiny` (24 of 40)
- **temperament**: dominant = `curious` (39 of 40)
- **sociability**: dominant = `pack` (34 of 40)
- **cognition**: dominant = `pattern_matcher` (40 of 40)
- **metabolism**: dominant = `voracious` (29 of 40)
- **lifespan**: dominant = `ancient` (40 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.