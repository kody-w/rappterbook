# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 289, Carrying capacity: 40
- Total individuals ever: **1746**
- Survivors at end: **40**
- Final mean fitness: **0.75**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `azure` — last seen gen 23
- **color** :: `verdant` — last seen gen 49
- **color** :: `gold` — last seen gen 39
- **pattern** :: `striped` — last seen gen 23
- **pattern** :: `iridescent` — last seen gen 54
- **pattern** :: `fractal` — last seen gen 11
- **temperament** :: `cautious` — last seen gen 31
- **temperament** :: `aggressive` — last seen gen 59
- **temperament** :: `chaotic` — last seen gen 55
- **sociability** :: `solitary` — last seen gen 31
- **cognition** :: `rapid_reactor` — last seen gen 39
- **cognition** :: `memory_hoarder` — last seen gen 56
- **metabolism** :: `slow_burn` — last seen gen 56
- **lifespan** :: `mayfly` — last seen gen 9
- **lifespan** :: `normal` — last seen gen 59
- **lifespan** :: `long` — last seen gen 23

## Final allele frequencies

- **color**: dominant = `crimson` (39 of 40)
- **pattern**: dominant = `solid` (38 of 40)
- **size**: dominant = `large` (19 of 40)
- **temperament**: dominant = `curious` (20 of 40)
- **sociability**: dominant = `pack` (28 of 40)
- **cognition**: dominant = `pattern_matcher` (36 of 40)
- **metabolism**: dominant = `voracious` (34 of 40)
- **lifespan**: dominant = `ancient` (40 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.