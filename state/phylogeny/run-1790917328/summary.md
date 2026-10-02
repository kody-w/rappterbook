# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 331, Carrying capacity: 40
- Total individuals ever: **1917**
- Survivors at end: **40**
- Final mean fitness: **0.7575**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **pattern** :: `striped` — last seen gen 20
- **pattern** :: `iridescent` — last seen gen 54
- **size** :: `medium` — last seen gen 19
- **temperament** :: `cautious` — last seen gen 29
- **temperament** :: `aggressive` — last seen gen 58
- **temperament** :: `chaotic` — last seen gen 22
- **cognition** :: `rapid_reactor` — last seen gen 53
- **metabolism** :: `torpor` — last seen gen 21
- **lifespan** :: `mayfly` — last seen gen 15
- **lifespan** :: `normal` — last seen gen 59
- **lifespan** :: `long` — last seen gen 55

## Final allele frequencies

- **color**: dominant = `azure` (18 of 40)
- **pattern**: dominant = `solid` (21 of 40)
- **size**: dominant = `large` (26 of 40)
- **temperament**: dominant = `peaceful` (27 of 40)
- **sociability**: dominant = `pack` (35 of 40)
- **cognition**: dominant = `pattern_matcher` (36 of 40)
- **metabolism**: dominant = `voracious` (34 of 40)
- **lifespan**: dominant = `ancient` (40 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.