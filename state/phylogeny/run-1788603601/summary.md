# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 232, Carrying capacity: 40
- Total individuals ever: **1877**
- Survivors at end: **40**
- Final mean fitness: **0.76**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **pattern** :: `striped` — last seen gen 25
- **pattern** :: `iridescent` — last seen gen 54
- **pattern** :: `fractal` — last seen gen 29
- **size** :: `tiny` — last seen gen 27
- **size** :: `small` — last seen gen 9
- **size** :: `giant` — last seen gen 57
- **temperament** :: `cautious` — last seen gen 59
- **temperament** :: `aggressive` — last seen gen 50
- **temperament** :: `chaotic` — last seen gen 59
- **sociability** :: `solitary` — last seen gen 49
- **sociability** :: `pair` — last seen gen 49
- **metabolism** :: `torpor` — last seen gen 26
- **lifespan** :: `mayfly` — last seen gen 11
- **lifespan** :: `normal` — last seen gen 18

## Final allele frequencies

- **color**: dominant = `crimson` (31 of 40)
- **pattern**: dominant = `solid` (38 of 40)
- **size**: dominant = `medium` (22 of 40)
- **temperament**: dominant = `peaceful` (20 of 40)
- **sociability**: dominant = `pack` (38 of 40)
- **cognition**: dominant = `pattern_matcher` (37 of 40)
- **metabolism**: dominant = `voracious` (26 of 40)
- **lifespan**: dominant = `ancient` (39 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.