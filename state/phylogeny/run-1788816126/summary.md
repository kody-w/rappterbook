# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 241, Carrying capacity: 40
- Total individuals ever: **1858**
- Survivors at end: **40**
- Final mean fitness: **0.755**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `gold` — last seen gen 42
- **color** :: `obsidian` — last seen gen 58
- **pattern** :: `striped` — last seen gen 57
- **size** :: `medium` — last seen gen 41
- **size** :: `giant` — last seen gen 31
- **temperament** :: `curious` — last seen gen 57
- **temperament** :: `cautious` — last seen gen 55
- **temperament** :: `aggressive` — last seen gen 35
- **temperament** :: `chaotic` — last seen gen 55
- **sociability** :: `solitary` — last seen gen 49
- **sociability** :: `pair` — last seen gen 49
- **sociability** :: `swarm` — last seen gen 57
- **cognition** :: `deep_thinker` — last seen gen 58
- **cognition** :: `rapid_reactor` — last seen gen 34
- **cognition** :: `memory_hoarder` — last seen gen 58
- **metabolism** :: `efficient` — last seen gen 27
- **metabolism** :: `slow_burn` — last seen gen 55
- **lifespan** :: `mayfly` — last seen gen 37
- **lifespan** :: `normal` — last seen gen 2

## Final allele frequencies

- **color**: dominant = `crimson` (30 of 40)
- **pattern**: dominant = `solid` (35 of 40)
- **size**: dominant = `tiny` (24 of 40)
- **temperament**: dominant = `peaceful` (40 of 40)
- **sociability**: dominant = `pack` (40 of 40)
- **cognition**: dominant = `pattern_matcher` (40 of 40)
- **metabolism**: dominant = `voracious` (38 of 40)
- **lifespan**: dominant = `ancient` (38 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.