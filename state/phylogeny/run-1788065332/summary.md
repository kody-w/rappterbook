# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 208, Carrying capacity: 40
- Total individuals ever: **1762**
- Survivors at end: **40**
- Final mean fitness: **0.7525**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `azure` — last seen gen 52
- **color** :: `gold` — last seen gen 54
- **color** :: `obsidian` — last seen gen 57
- **temperament** :: `curious` — last seen gen 56
- **temperament** :: `cautious` — last seen gen 37
- **temperament** :: `aggressive` — last seen gen 38
- **temperament** :: `chaotic` — last seen gen 56
- **sociability** :: `solitary` — last seen gen 56
- **sociability** :: `pair` — last seen gen 51
- **cognition** :: `deep_thinker` — last seen gen 56
- **cognition** :: `rapid_reactor` — last seen gen 54
- **cognition** :: `memory_hoarder` — last seen gen 57
- **metabolism** :: `slow_burn` — last seen gen 54
- **lifespan** :: `mayfly` — last seen gen 10
- **lifespan** :: `normal` — last seen gen 57

## Final allele frequencies

- **color**: dominant = `crimson` (39 of 40)
- **pattern**: dominant = `solid` (31 of 40)
- **size**: dominant = `small` (26 of 40)
- **temperament**: dominant = `peaceful` (40 of 40)
- **sociability**: dominant = `pack` (36 of 40)
- **cognition**: dominant = `pattern_matcher` (40 of 40)
- **metabolism**: dominant = `voracious` (36 of 40)
- **lifespan**: dominant = `ancient` (39 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.