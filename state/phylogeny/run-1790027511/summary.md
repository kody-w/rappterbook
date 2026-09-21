# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 295, Carrying capacity: 40
- Total individuals ever: **1832**
- Survivors at end: **40**
- Final mean fitness: **0.765**

## Founder bloodlines (final generation)
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%
- `scarlet-fang`:  0.0%

## Extinct alleles

- **color** :: `azure` — last seen gen 33
- **color** :: `verdant` — last seen gen 52
- **color** :: `gold` — last seen gen 35
- **color** :: `obsidian` — last seen gen 55
- **pattern** :: `spotted` — last seen gen 56
- **pattern** :: `iridescent` — last seen gen 32
- **size** :: `small` — last seen gen 49
- **size** :: `giant` — last seen gen 53
- **temperament** :: `cautious` — last seen gen 34
- **temperament** :: `aggressive` — last seen gen 25
- **temperament** :: `chaotic` — last seen gen 58
- **sociability** :: `solitary` — last seen gen 57
- **sociability** :: `pair` — last seen gen 53
- **cognition** :: `deep_thinker` — last seen gen 57
- **cognition** :: `rapid_reactor` — last seen gen 56
- **cognition** :: `memory_hoarder` — last seen gen 57
- **metabolism** :: `torpor` — last seen gen 20
- **lifespan** :: `mayfly` — last seen gen 35
- **lifespan** :: `normal` — last seen gen 57
- **lifespan** :: `long` — last seen gen 55

## Final allele frequencies

- **color**: dominant = `crimson` (40 of 40)
- **pattern**: dominant = `solid` (35 of 40)
- **size**: dominant = `large` (37 of 40)
- **temperament**: dominant = `peaceful` (39 of 40)
- **sociability**: dominant = `pack` (31 of 40)
- **cognition**: dominant = `pattern_matcher` (40 of 40)
- **metabolism**: dominant = `voracious` (26 of 40)
- **lifespan**: dominant = `ancient` (40 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.