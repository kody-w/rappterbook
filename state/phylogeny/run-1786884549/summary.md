# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 163, Carrying capacity: 40
- Total individuals ever: **1834**
- Survivors at end: **40**
- Final mean fitness: **0.7825**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `azure` — last seen gen 58
- **pattern** :: `solid` — last seen gen 30
- **pattern** :: `spotted` — last seen gen 58
- **size** :: `large` — last seen gen 54
- **size** :: `giant` — last seen gen 58
- **temperament** :: `cautious` — last seen gen 35
- **temperament** :: `aggressive` — last seen gen 56
- **temperament** :: `chaotic` — last seen gen 58
- **sociability** :: `solitary` — last seen gen 49
- **sociability** :: `pair` — last seen gen 49
- **cognition** :: `rapid_reactor` — last seen gen 41
- **cognition** :: `memory_hoarder` — last seen gen 58
- **metabolism** :: `efficient` — last seen gen 32
- **metabolism** :: `slow_burn` — last seen gen 50
- **lifespan** :: `mayfly` — last seen gen 6
- **lifespan** :: `normal` — last seen gen 59

## Final allele frequencies

- **color**: dominant = `crimson` (35 of 40)
- **pattern**: dominant = `striped` (28 of 40)
- **size**: dominant = `tiny` (37 of 40)
- **temperament**: dominant = `peaceful` (37 of 40)
- **sociability**: dominant = `pack` (30 of 40)
- **cognition**: dominant = `pattern_matcher` (37 of 40)
- **metabolism**: dominant = `voracious` (36 of 40)
- **lifespan**: dominant = `ancient` (27 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.