# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 349, Carrying capacity: 40
- Total individuals ever: **2021**
- Survivors at end: **40**
- Final mean fitness: **0.7612**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`:  0.0%
- `gold-storm`:  0.0%

## Extinct alleles

- **size** :: `giant` — last seen gen 55
- **temperament** :: `cautious` — last seen gen 55
- **temperament** :: `aggressive` — last seen gen 17
- **temperament** :: `peaceful` — last seen gen 59
- **temperament** :: `chaotic` — last seen gen 55
- **sociability** :: `solitary` — last seen gen 18
- **sociability** :: `pair` — last seen gen 55
- **cognition** :: `deep_thinker` — last seen gen 55
- **cognition** :: `rapid_reactor` — last seen gen 20
- **cognition** :: `memory_hoarder` — last seen gen 55
- **metabolism** :: `efficient` — last seen gen 54
- **lifespan** :: `mayfly` — last seen gen 6
- **lifespan** :: `normal` — last seen gen 52
- **lifespan** :: `long` — last seen gen 29

## Final allele frequencies

- **color**: dominant = `crimson` (23 of 40)
- **pattern**: dominant = `solid` (22 of 40)
- **size**: dominant = `tiny` (32 of 40)
- **temperament**: dominant = `curious` (40 of 40)
- **sociability**: dominant = `pack` (28 of 40)
- **cognition**: dominant = `pattern_matcher` (40 of 40)
- **metabolism**: dominant = `voracious` (34 of 40)
- **lifespan**: dominant = `ancient` (40 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.