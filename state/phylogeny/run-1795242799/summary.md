# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 487, Carrying capacity: 40
- Total individuals ever: **1986**
- Survivors at end: **40**
- Final mean fitness: **0.75**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `azure` — last seen gen 47
- **color** :: `gold` — last seen gen 52
- **color** :: `obsidian` — last seen gen 55
- **pattern** :: `solid` — last seen gen 23
- **temperament** :: `curious` — last seen gen 56
- **temperament** :: `cautious` — last seen gen 55
- **temperament** :: `aggressive` — last seen gen 29
- **temperament** :: `chaotic` — last seen gen 56
- **sociability** :: `solitary` — last seen gen 56
- **sociability** :: `pair` — last seen gen 50
- **cognition** :: `deep_thinker` — last seen gen 56
- **cognition** :: `rapid_reactor` — last seen gen 11
- **cognition** :: `memory_hoarder` — last seen gen 56
- **metabolism** :: `slow_burn` — last seen gen 56
- **metabolism** :: `torpor` — last seen gen 56
- **lifespan** :: `mayfly` — last seen gen 18
- **lifespan** :: `normal` — last seen gen 56
- **lifespan** :: `long` — last seen gen 53

## Final allele frequencies

- **color**: dominant = `crimson` (38 of 40)
- **pattern**: dominant = `striped` (34 of 40)
- **size**: dominant = `tiny` (20 of 40)
- **temperament**: dominant = `peaceful` (40 of 40)
- **sociability**: dominant = `pack` (39 of 40)
- **cognition**: dominant = `pattern_matcher` (40 of 40)
- **metabolism**: dominant = `efficient` (35 of 40)
- **lifespan**: dominant = `ancient` (40 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.