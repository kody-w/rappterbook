# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 157, Carrying capacity: 40
- Total individuals ever: **1755**
- Survivors at end: **40**
- Final mean fitness: **0.7662**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `gold` — last seen gen 23
- **pattern** :: `striped` — last seen gen 26
- **pattern** :: `fractal` — last seen gen 45
- **size** :: `small` — last seen gen 12
- **temperament** :: `cautious` — last seen gen 32
- **temperament** :: `aggressive` — last seen gen 15
- **temperament** :: `chaotic` — last seen gen 45
- **sociability** :: `solitary` — last seen gen 49
- **sociability** :: `pair` — last seen gen 51
- **cognition** :: `rapid_reactor` — last seen gen 44
- **cognition** :: `memory_hoarder` — last seen gen 54
- **metabolism** :: `efficient` — last seen gen 27
- **lifespan** :: `mayfly` — last seen gen 33
- **lifespan** :: `normal` — last seen gen 54

## Final allele frequencies

- **color**: dominant = `crimson` (32 of 40)
- **pattern**: dominant = `solid` (36 of 40)
- **size**: dominant = `large` (19 of 40)
- **temperament**: dominant = `curious` (32 of 40)
- **sociability**: dominant = `pack` (36 of 40)
- **cognition**: dominant = `pattern_matcher` (39 of 40)
- **metabolism**: dominant = `voracious` (34 of 40)
- **lifespan**: dominant = `ancient` (38 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.