# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 151, Carrying capacity: 40
- Total individuals ever: **1869**
- Survivors at end: **40**
- Final mean fitness: **0.75**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `obsidian` — last seen gen 59
- **pattern** :: `striped` — last seen gen 42
- **pattern** :: `spotted` — last seen gen 55
- **pattern** :: `iridescent` — last seen gen 37
- **pattern** :: `fractal` — last seen gen 56
- **size** :: `tiny` — last seen gen 24
- **temperament** :: `cautious` — last seen gen 38
- **temperament** :: `aggressive` — last seen gen 33
- **temperament** :: `chaotic` — last seen gen 59
- **sociability** :: `solitary` — last seen gen 14
- **sociability** :: `pair` — last seen gen 49
- **cognition** :: `pattern_matcher` — last seen gen 42
- **cognition** :: `rapid_reactor` — last seen gen 41
- **metabolism** :: `efficient` — last seen gen 38
- **metabolism** :: `slow_burn` — last seen gen 52
- **lifespan** :: `mayfly` — last seen gen 37
- **lifespan** :: `normal` — last seen gen 38
- **lifespan** :: `long` — last seen gen 38

## Final allele frequencies

- **color**: dominant = `azure` (32 of 40)
- **pattern**: dominant = `solid` (40 of 40)
- **size**: dominant = `large` (22 of 40)
- **temperament**: dominant = `curious` (34 of 40)
- **sociability**: dominant = `pack` (39 of 40)
- **cognition**: dominant = `deep_thinker` (26 of 40)
- **metabolism**: dominant = `voracious` (39 of 40)
- **lifespan**: dominant = `ancient` (40 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.