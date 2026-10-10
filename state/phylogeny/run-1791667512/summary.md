# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 358, Carrying capacity: 40
- Total individuals ever: **1898**
- Survivors at end: **40**
- Final mean fitness: **0.7725**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `azure` — last seen gen 40
- **color** :: `obsidian` — last seen gen 55
- **pattern** :: `iridescent` — last seen gen 56
- **pattern** :: `fractal` — last seen gen 54
- **size** :: `giant` — last seen gen 51
- **temperament** :: `curious` — last seen gen 57
- **temperament** :: `cautious` — last seen gen 49
- **temperament** :: `aggressive` — last seen gen 29
- **temperament** :: `chaotic` — last seen gen 52
- **sociability** :: `solitary` — last seen gen 54
- **sociability** :: `pair` — last seen gen 41
- **cognition** :: `deep_thinker` — last seen gen 57
- **cognition** :: `rapid_reactor` — last seen gen 41
- **cognition** :: `memory_hoarder` — last seen gen 56
- **metabolism** :: `efficient` — last seen gen 31
- **metabolism** :: `torpor` — last seen gen 22
- **lifespan** :: `mayfly` — last seen gen 7
- **lifespan** :: `normal` — last seen gen 50
- **lifespan** :: `long` — last seen gen 31

## Final allele frequencies

- **color**: dominant = `crimson` (33 of 40)
- **pattern**: dominant = `solid` (34 of 40)
- **size**: dominant = `tiny` (26 of 40)
- **temperament**: dominant = `peaceful` (40 of 40)
- **sociability**: dominant = `pack` (39 of 40)
- **cognition**: dominant = `pattern_matcher` (40 of 40)
- **metabolism**: dominant = `voracious` (34 of 40)
- **lifespan**: dominant = `ancient` (40 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.