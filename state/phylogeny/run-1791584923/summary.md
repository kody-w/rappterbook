# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 355, Carrying capacity: 40
- Total individuals ever: **1834**
- Survivors at end: **40**
- Final mean fitness: **0.76**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `gold` — last seen gen 55
- **color** :: `obsidian` — last seen gen 55
- **pattern** :: `spotted` — last seen gen 32
- **pattern** :: `iridescent` — last seen gen 57
- **size** :: `small` — last seen gen 40
- **size** :: `large` — last seen gen 55
- **size** :: `giant` — last seen gen 58
- **temperament** :: `cautious` — last seen gen 33
- **temperament** :: `aggressive` — last seen gen 33
- **temperament** :: `chaotic` — last seen gen 42
- **sociability** :: `solitary` — last seen gen 50
- **sociability** :: `pair` — last seen gen 50
- **sociability** :: `swarm` — last seen gen 58
- **cognition** :: `rapid_reactor` — last seen gen 13
- **cognition** :: `memory_hoarder` — last seen gen 56
- **metabolism** :: `torpor` — last seen gen 56
- **lifespan** :: `mayfly` — last seen gen 35
- **lifespan** :: `normal` — last seen gen 56

## Final allele frequencies

- **color**: dominant = `crimson` (37 of 40)
- **pattern**: dominant = `solid` (33 of 40)
- **size**: dominant = `tiny` (38 of 40)
- **temperament**: dominant = `peaceful` (26 of 40)
- **sociability**: dominant = `pack` (40 of 40)
- **cognition**: dominant = `pattern_matcher` (28 of 40)
- **metabolism**: dominant = `voracious` (21 of 40)
- **lifespan**: dominant = `ancient` (39 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.