# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 133, Carrying capacity: 40
- Total individuals ever: **1875**
- Survivors at end: **40**
- Final mean fitness: **0.7638**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `verdant` — last seen gen 43
- **color** :: `gold` — last seen gen 59
- **color** :: `obsidian` — last seen gen 10
- **pattern** :: `iridescent` — last seen gen 56
- **pattern** :: `fractal` — last seen gen 43
- **temperament** :: `cautious` — last seen gen 13
- **temperament** :: `aggressive` — last seen gen 54
- **temperament** :: `chaotic` — last seen gen 50
- **sociability** :: `pair` — last seen gen 16
- **cognition** :: `rapid_reactor` — last seen gen 58
- **metabolism** :: `efficient` — last seen gen 53
- **lifespan** :: `mayfly` — last seen gen 37
- **lifespan** :: `normal` — last seen gen 19

## Final allele frequencies

- **color**: dominant = `crimson` (39 of 40)
- **pattern**: dominant = `solid` (32 of 40)
- **size**: dominant = `tiny` (18 of 40)
- **temperament**: dominant = `peaceful` (38 of 40)
- **sociability**: dominant = `pack` (38 of 40)
- **cognition**: dominant = `pattern_matcher` (33 of 40)
- **metabolism**: dominant = `voracious` (34 of 40)
- **lifespan**: dominant = `ancient` (39 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.