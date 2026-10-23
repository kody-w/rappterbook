# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 403, Carrying capacity: 40
- Total individuals ever: **1827**
- Survivors at end: **40**
- Final mean fitness: **0.7537**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `gold` — last seen gen 50
- **color** :: `obsidian` — last seen gen 8
- **pattern** :: `spotted` — last seen gen 54
- **size** :: `small` — last seen gen 50
- **size** :: `large` — last seen gen 54
- **temperament** :: `cautious` — last seen gen 34
- **temperament** :: `aggressive` — last seen gen 59
- **temperament** :: `chaotic` — last seen gen 28
- **sociability** :: `solitary` — last seen gen 55
- **sociability** :: `pair` — last seen gen 50
- **cognition** :: `deep_thinker` — last seen gen 55
- **cognition** :: `rapid_reactor` — last seen gen 35
- **cognition** :: `memory_hoarder` — last seen gen 55
- **lifespan** :: `mayfly` — last seen gen 19
- **lifespan** :: `normal` — last seen gen 53
- **lifespan** :: `long` — last seen gen 36

## Final allele frequencies

- **color**: dominant = `crimson` (29 of 40)
- **pattern**: dominant = `solid` (36 of 40)
- **size**: dominant = `tiny` (30 of 40)
- **temperament**: dominant = `curious` (36 of 40)
- **sociability**: dominant = `pack` (27 of 40)
- **cognition**: dominant = `pattern_matcher` (40 of 40)
- **metabolism**: dominant = `voracious` (31 of 40)
- **lifespan**: dominant = `ancient` (40 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.