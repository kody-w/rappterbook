# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 433, Carrying capacity: 40
- Total individuals ever: **1903**
- Survivors at end: **40**
- Final mean fitness: **0.7525**

## Founder bloodlines (final generation)
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%
- `scarlet-fang`:  0.0%

## Extinct alleles

- **color** :: `verdant` — last seen gen 57
- **color** :: `gold` — last seen gen 55
- **color** :: `obsidian` — last seen gen 20
- **pattern** :: `solid` — last seen gen 52
- **pattern** :: `iridescent` — last seen gen 56
- **size** :: `tiny` — last seen gen 56
- **size** :: `medium` — last seen gen 14
- **temperament** :: `curious` — last seen gen 58
- **temperament** :: `cautious` — last seen gen 33
- **temperament** :: `aggressive` — last seen gen 12
- **temperament** :: `chaotic` — last seen gen 55
- **sociability** :: `solitary` — last seen gen 54
- **sociability** :: `pair` — last seen gen 45
- **cognition** :: `deep_thinker` — last seen gen 58
- **cognition** :: `rapid_reactor` — last seen gen 58
- **cognition** :: `memory_hoarder` — last seen gen 58
- **metabolism** :: `efficient` — last seen gen 24
- **metabolism** :: `slow_burn` — last seen gen 24
- **metabolism** :: `torpor` — last seen gen 24
- **lifespan** :: `mayfly` — last seen gen 1
- **lifespan** :: `normal` — last seen gen 16

## Final allele frequencies

- **color**: dominant = `crimson` (29 of 40)
- **pattern**: dominant = `striped` (38 of 40)
- **size**: dominant = `large` (27 of 40)
- **temperament**: dominant = `peaceful` (40 of 40)
- **sociability**: dominant = `pack` (33 of 40)
- **cognition**: dominant = `pattern_matcher` (40 of 40)
- **metabolism**: dominant = `voracious` (40 of 40)
- **lifespan**: dominant = `ancient` (39 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.