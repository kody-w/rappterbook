# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 268, Carrying capacity: 40
- Total individuals ever: **1836**
- Survivors at end: **40**
- Final mean fitness: **0.7562**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `azure-mind`:  0.0%
- `gold-storm`:  0.0%

## Extinct alleles

- **color** :: `azure` — last seen gen 10
- **color** :: `obsidian` — never appeared after gen 0
- **pattern** :: `striped` — last seen gen 56
- **pattern** :: `spotted` — last seen gen 59
- **size** :: `small` — last seen gen 57
- **size** :: `medium` — last seen gen 56
- **temperament** :: `cautious` — last seen gen 59
- **temperament** :: `aggressive` — last seen gen 59
- **temperament** :: `chaotic` — last seen gen 59
- **sociability** :: `solitary` — last seen gen 49
- **sociability** :: `pair` — last seen gen 10
- **sociability** :: `swarm` — last seen gen 52
- **cognition** :: `deep_thinker` — last seen gen 58
- **cognition** :: `rapid_reactor` — last seen gen 33
- **cognition** :: `memory_hoarder` — last seen gen 58
- **metabolism** :: `torpor` — last seen gen 51
- **lifespan** :: `mayfly` — last seen gen 35
- **lifespan** :: `normal` — last seen gen 33

## Final allele frequencies

- **color**: dominant = `crimson` (36 of 40)
- **pattern**: dominant = `solid` (36 of 40)
- **size**: dominant = `tiny` (33 of 40)
- **temperament**: dominant = `curious` (38 of 40)
- **sociability**: dominant = `pack` (40 of 40)
- **cognition**: dominant = `pattern_matcher` (40 of 40)
- **metabolism**: dominant = `efficient` (28 of 40)
- **lifespan**: dominant = `ancient` (39 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.