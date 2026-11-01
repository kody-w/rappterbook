# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 436, Carrying capacity: 40
- Total individuals ever: **1939**
- Survivors at end: **40**
- Final mean fitness: **0.7688**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `verdant` — last seen gen 55
- **color** :: `obsidian` — last seen gen 57
- **pattern** :: `striped` — last seen gen 53
- **pattern** :: `fractal` — last seen gen 44
- **size** :: `small` — last seen gen 55
- **size** :: `medium` — last seen gen 37
- **temperament** :: `curious` — last seen gen 44
- **temperament** :: `cautious` — last seen gen 38
- **temperament** :: `aggressive` — last seen gen 56
- **temperament** :: `chaotic` — last seen gen 57
- **sociability** :: `solitary` — last seen gen 54
- **sociability** :: `pair` — last seen gen 51
- **cognition** :: `deep_thinker` — last seen gen 57
- **cognition** :: `rapid_reactor` — last seen gen 14
- **cognition** :: `memory_hoarder` — last seen gen 57
- **metabolism** :: `efficient` — last seen gen 52
- **lifespan** :: `mayfly` — never appeared after gen 0
- **lifespan** :: `normal` — last seen gen 57
- **lifespan** :: `long` — last seen gen 57

## Final allele frequencies

- **color**: dominant = `crimson` (36 of 40)
- **pattern**: dominant = `solid` (31 of 40)
- **size**: dominant = `tiny` (34 of 40)
- **temperament**: dominant = `peaceful` (40 of 40)
- **sociability**: dominant = `pack` (34 of 40)
- **cognition**: dominant = `pattern_matcher` (40 of 40)
- **metabolism**: dominant = `voracious` (32 of 40)
- **lifespan**: dominant = `ancient` (40 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.