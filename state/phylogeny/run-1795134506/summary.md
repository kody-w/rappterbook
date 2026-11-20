# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 484, Carrying capacity: 40
- Total individuals ever: **2069**
- Survivors at end: **40**
- Final mean fitness: **0.7575**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `azure` — last seen gen 26
- **color** :: `gold` — last seen gen 52
- **color** :: `obsidian` — last seen gen 38
- **pattern** :: `spotted` — last seen gen 12
- **pattern** :: `fractal` — last seen gen 53
- **size** :: `tiny` — last seen gen 49
- **temperament** :: `curious` — last seen gen 58
- **temperament** :: `cautious` — last seen gen 59
- **temperament** :: `chaotic` — last seen gen 55
- **sociability** :: `solitary` — last seen gen 49
- **sociability** :: `pair` — last seen gen 49
- **cognition** :: `rapid_reactor` — last seen gen 41
- **metabolism** :: `efficient` — last seen gen 54
- **lifespan** :: `mayfly` — last seen gen 39
- **lifespan** :: `normal` — last seen gen 59
- **lifespan** :: `long` — last seen gen 55

## Final allele frequencies

- **color**: dominant = `crimson` (37 of 40)
- **pattern**: dominant = `solid` (34 of 40)
- **size**: dominant = `large` (19 of 40)
- **temperament**: dominant = `peaceful` (39 of 40)
- **sociability**: dominant = `pack` (26 of 40)
- **cognition**: dominant = `pattern_matcher` (35 of 40)
- **metabolism**: dominant = `voracious` (36 of 40)
- **lifespan**: dominant = `ancient` (40 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.