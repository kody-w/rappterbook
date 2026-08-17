# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 166, Carrying capacity: 40
- Total individuals ever: **1840**
- Survivors at end: **40**
- Final mean fitness: **0.765**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `azure` — last seen gen 36
- **color** :: `gold` — last seen gen 42
- **pattern** :: `spotted` — last seen gen 44
- **pattern** :: `iridescent` — last seen gen 33
- **size** :: `small` — last seen gen 49
- **size** :: `medium` — last seen gen 9
- **temperament** :: `cautious` — last seen gen 59
- **temperament** :: `aggressive` — last seen gen 58
- **temperament** :: `chaotic` — last seen gen 55
- **sociability** :: `solitary` — last seen gen 54
- **sociability** :: `pair` — last seen gen 50
- **sociability** :: `swarm` — last seen gen 54
- **cognition** :: `rapid_reactor` — last seen gen 45
- **cognition** :: `memory_hoarder` — last seen gen 55
- **metabolism** :: `efficient` — last seen gen 27
- **lifespan** :: `mayfly` — last seen gen 37
- **lifespan** :: `normal` — last seen gen 51
- **lifespan** :: `long` — last seen gen 55

## Final allele frequencies

- **color**: dominant = `crimson` (35 of 40)
- **pattern**: dominant = `solid` (33 of 40)
- **size**: dominant = `large` (23 of 40)
- **temperament**: dominant = `curious` (23 of 40)
- **sociability**: dominant = `pack` (40 of 40)
- **cognition**: dominant = `pattern_matcher` (38 of 40)
- **metabolism**: dominant = `voracious` (34 of 40)
- **lifespan**: dominant = `ancient` (40 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.