# Egg Phylogeny — Run Summary

- Generations simulated: **30**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 103, Carrying capacity: 20
- Total individuals ever: **458**
- Survivors at end: **20**
- Final mean fitness: **0.7275**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `gold` — last seen gen 8
- **pattern** :: `spotted` — last seen gen 23
- **pattern** :: `iridescent` — last seen gen 8
- **pattern** :: `fractal` — last seen gen 10
- **size** :: `tiny` — last seen gen 28
- **size** :: `small` — last seen gen 26
- **size** :: `medium` — last seen gen 12
- **temperament** :: `curious` — last seen gen 18
- **temperament** :: `peaceful` — last seen gen 12
- **temperament** :: `chaotic` — last seen gen 18
- **sociability** :: `solitary` — last seen gen 9
- **sociability** :: `pair` — last seen gen 12
- **sociability** :: `pack` — last seen gen 24
- **cognition** :: `pattern_matcher` — last seen gen 7
- **cognition** :: `rapid_reactor` — last seen gen 28
- **cognition** :: `memory_hoarder` — last seen gen 12
- **metabolism** :: `efficient` — last seen gen 28
- **metabolism** :: `slow_burn` — last seen gen 19
- **metabolism** :: `torpor` — last seen gen 14
- **lifespan** :: `mayfly` — last seen gen 9
- **lifespan** :: `normal` — last seen gen 6

## Final allele frequencies

- **color**: dominant = `crimson` (10 of 20)
- **pattern**: dominant = `solid` (19 of 20)
- **size**: dominant = `large` (17 of 20)
- **temperament**: dominant = `cautious` (14 of 20)
- **sociability**: dominant = `swarm` (20 of 20)
- **cognition**: dominant = `deep_thinker` (20 of 20)
- **metabolism**: dominant = `voracious` (20 of 20)
- **lifespan**: dominant = `ancient` (11 of 20)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.