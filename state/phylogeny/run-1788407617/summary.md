# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 223, Carrying capacity: 40
- Total individuals ever: **2026**
- Survivors at end: **40**
- Final mean fitness: **0.755**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `gold` — last seen gen 13
- **color** :: `obsidian` — last seen gen 50
- **pattern** :: `fractal` — last seen gen 54
- **size** :: `small` — last seen gen 17
- **size** :: `large` — last seen gen 58
- **size** :: `giant` — last seen gen 54
- **temperament** :: `cautious` — last seen gen 38
- **temperament** :: `aggressive` — last seen gen 38
- **temperament** :: `chaotic` — last seen gen 58
- **sociability** :: `pair` — last seen gen 54
- **cognition** :: `rapid_reactor` — last seen gen 58
- **metabolism** :: `efficient` — last seen gen 58
- **metabolism** :: `slow_burn` — last seen gen 30
- **metabolism** :: `torpor` — last seen gen 29
- **lifespan** :: `mayfly` — last seen gen 39
- **lifespan** :: `normal` — last seen gen 59

## Final allele frequencies

- **color**: dominant = `crimson` (34 of 40)
- **pattern**: dominant = `solid` (33 of 40)
- **size**: dominant = `tiny` (26 of 40)
- **temperament**: dominant = `peaceful` (32 of 40)
- **sociability**: dominant = `pack` (36 of 40)
- **cognition**: dominant = `pattern_matcher` (35 of 40)
- **metabolism**: dominant = `voracious` (40 of 40)
- **lifespan**: dominant = `ancient` (38 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.