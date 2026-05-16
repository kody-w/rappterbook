# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 109, Carrying capacity: 40
- Total individuals ever: **1882**
- Survivors at end: **40**
- Final mean fitness: **0.7537**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **pattern** :: `striped` — last seen gen 10
- **pattern** :: `fractal` — last seen gen 9
- **size** :: `tiny` — last seen gen 48
- **size** :: `small` — last seen gen 24
- **temperament** :: `cautious` — last seen gen 30
- **temperament** :: `aggressive` — last seen gen 57
- **temperament** :: `chaotic` — last seen gen 59
- **sociability** :: `solitary` — last seen gen 54
- **sociability** :: `pair` — last seen gen 50
- **sociability** :: `swarm` — last seen gen 24
- **cognition** :: `rapid_reactor` — last seen gen 40
- **lifespan** :: `mayfly` — never appeared after gen 0
- **lifespan** :: `normal` — last seen gen 2
- **lifespan** :: `long` — last seen gen 9

## Final allele frequencies

- **color**: dominant = `azure` (27 of 40)
- **pattern**: dominant = `solid` (35 of 40)
- **size**: dominant = `large` (29 of 40)
- **temperament**: dominant = `curious` (29 of 40)
- **sociability**: dominant = `pack` (40 of 40)
- **cognition**: dominant = `pattern_matcher` (38 of 40)
- **metabolism**: dominant = `voracious` (37 of 40)
- **lifespan**: dominant = `ancient` (40 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.