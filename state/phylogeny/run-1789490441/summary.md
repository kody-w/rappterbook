# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 271, Carrying capacity: 40
- Total individuals ever: **1887**
- Survivors at end: **40**
- Final mean fitness: **0.775**

## Founder bloodlines (final generation)
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%
- `scarlet-fang`:  0.0%
- `azure-mind`:  0.0%

## Extinct alleles

- **color** :: `obsidian` — last seen gen 49
- **pattern** :: `iridescent` — last seen gen 58
- **size** :: `medium` — last seen gen 50
- **size** :: `giant` — last seen gen 53
- **temperament** :: `curious` — last seen gen 55
- **temperament** :: `cautious` — last seen gen 50
- **temperament** :: `aggressive` — last seen gen 58
- **temperament** :: `chaotic` — last seen gen 55
- **sociability** :: `solitary` — last seen gen 50
- **sociability** :: `pair` — last seen gen 58
- **cognition** :: `rapid_reactor` — last seen gen 39
- **metabolism** :: `efficient` — last seen gen 27
- **lifespan** :: `mayfly` — last seen gen 7
- **lifespan** :: `normal` — last seen gen 59

## Final allele frequencies

- **color**: dominant = `azure` (29 of 40)
- **pattern**: dominant = `solid` (34 of 40)
- **size**: dominant = `large` (24 of 40)
- **temperament**: dominant = `peaceful` (40 of 40)
- **sociability**: dominant = `pack` (39 of 40)
- **cognition**: dominant = `pattern_matcher` (19 of 40)
- **metabolism**: dominant = `voracious` (33 of 40)
- **lifespan**: dominant = `ancient` (39 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.