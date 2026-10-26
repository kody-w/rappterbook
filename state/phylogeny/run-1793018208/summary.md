# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 415, Carrying capacity: 40
- Total individuals ever: **1803**
- Survivors at end: **40**
- Final mean fitness: **0.7638**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `obsidian` — last seen gen 23
- **pattern** :: `spotted` — last seen gen 52
- **pattern** :: `iridescent` — last seen gen 58
- **temperament** :: `curious` — last seen gen 58
- **temperament** :: `cautious` — last seen gen 58
- **temperament** :: `aggressive` — last seen gen 30
- **temperament** :: `chaotic` — last seen gen 58
- **sociability** :: `solitary` — last seen gen 31
- **sociability** :: `pair` — last seen gen 13
- **cognition** :: `deep_thinker` — last seen gen 58
- **cognition** :: `rapid_reactor` — last seen gen 42
- **cognition** :: `memory_hoarder` — last seen gen 52
- **metabolism** :: `efficient` — last seen gen 29
- **lifespan** :: `mayfly` — last seen gen 33
- **lifespan** :: `normal` — last seen gen 19

## Final allele frequencies

- **color**: dominant = `crimson` (36 of 40)
- **pattern**: dominant = `solid` (28 of 40)
- **size**: dominant = `tiny` (15 of 40)
- **temperament**: dominant = `peaceful` (40 of 40)
- **sociability**: dominant = `pack` (37 of 40)
- **cognition**: dominant = `pattern_matcher` (40 of 40)
- **metabolism**: dominant = `voracious` (36 of 40)
- **lifespan**: dominant = `ancient` (39 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.