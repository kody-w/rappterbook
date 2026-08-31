# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 214, Carrying capacity: 40
- Total individuals ever: **1766**
- Survivors at end: **40**
- Final mean fitness: **0.8063**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `gold` — last seen gen 55
- **color** :: `obsidian` — last seen gen 53
- **pattern** :: `spotted` — last seen gen 51
- **pattern** :: `iridescent` — last seen gen 58
- **pattern** :: `fractal` — last seen gen 18
- **size** :: `small` — last seen gen 55
- **temperament** :: `cautious` — last seen gen 50
- **temperament** :: `aggressive` — last seen gen 59
- **temperament** :: `chaotic` — last seen gen 55
- **sociability** :: `solitary` — last seen gen 5
- **sociability** :: `pair` — last seen gen 55
- **cognition** :: `deep_thinker` — last seen gen 59
- **cognition** :: `rapid_reactor` — last seen gen 43
- **cognition** :: `memory_hoarder` — last seen gen 55
- **lifespan** :: `mayfly` — last seen gen 38
- **lifespan** :: `normal` — last seen gen 9
- **lifespan** :: `long` — last seen gen 56

## Final allele frequencies

- **color**: dominant = `azure` (30 of 40)
- **pattern**: dominant = `solid` (33 of 40)
- **size**: dominant = `tiny` (24 of 40)
- **temperament**: dominant = `curious` (37 of 40)
- **sociability**: dominant = `pack` (38 of 40)
- **cognition**: dominant = `pattern_matcher` (40 of 40)
- **metabolism**: dominant = `voracious` (20 of 40)
- **lifespan**: dominant = `ancient` (40 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.