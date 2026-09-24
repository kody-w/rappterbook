# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 304, Carrying capacity: 40
- Total individuals ever: **1982**
- Survivors at end: **40**
- Final mean fitness: **0.7537**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `azure` — last seen gen 31
- **pattern** :: `spotted` — last seen gen 41
- **pattern** :: `iridescent` — last seen gen 54
- **size** :: `tiny` — last seen gen 55
- **size** :: `small` — last seen gen 55
- **temperament** :: `cautious` — last seen gen 32
- **temperament** :: `aggressive` — last seen gen 59
- **temperament** :: `chaotic` — last seen gen 59
- **sociability** :: `pair` — last seen gen 49
- **cognition** :: `memory_hoarder` — last seen gen 57
- **metabolism** :: `efficient` — last seen gen 55
- **metabolism** :: `torpor` — last seen gen 51
- **lifespan** :: `mayfly` — last seen gen 7
- **lifespan** :: `normal` — last seen gen 57
- **lifespan** :: `long` — last seen gen 57

## Final allele frequencies

- **color**: dominant = `crimson` (36 of 40)
- **pattern**: dominant = `solid` (34 of 40)
- **size**: dominant = `large` (20 of 40)
- **temperament**: dominant = `curious` (30 of 40)
- **sociability**: dominant = `pack` (38 of 40)
- **cognition**: dominant = `pattern_matcher` (37 of 40)
- **metabolism**: dominant = `voracious` (39 of 40)
- **lifespan**: dominant = `ancient` (40 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.