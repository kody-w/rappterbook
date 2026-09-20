# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 292, Carrying capacity: 40
- Total individuals ever: **1736**
- Survivors at end: **40**
- Final mean fitness: **0.7638**

## Founder bloodlines (final generation)
- `azure-mind`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%
- `scarlet-fang`:  0.0%
- `verdant-vow`:  0.0%

## Extinct alleles

- **color** :: `crimson` — never appeared after gen 0
- **color** :: `verdant` — last seen gen 59
- **pattern** :: `spotted` — last seen gen 53
- **pattern** :: `iridescent` — last seen gen 52
- **pattern** :: `fractal` — last seen gen 47
- **size** :: `small` — last seen gen 46
- **temperament** :: `curious` — last seen gen 57
- **temperament** :: `cautious` — last seen gen 30
- **temperament** :: `aggressive` — last seen gen 54
- **temperament** :: `chaotic` — last seen gen 55
- **sociability** :: `solitary` — last seen gen 54
- **sociability** :: `pair` — last seen gen 43
- **sociability** :: `pack` — last seen gen 46
- **cognition** :: `deep_thinker` — last seen gen 58
- **cognition** :: `rapid_reactor` — last seen gen 57
- **metabolism** :: `efficient` — last seen gen 29
- **metabolism** :: `torpor` — last seen gen 49
- **lifespan** :: `mayfly` — last seen gen 16
- **lifespan** :: `normal` — last seen gen 58

## Final allele frequencies

- **color**: dominant = `azure` (36 of 40)
- **pattern**: dominant = `solid` (33 of 40)
- **size**: dominant = `medium` (18 of 40)
- **temperament**: dominant = `peaceful` (40 of 40)
- **sociability**: dominant = `swarm` (40 of 40)
- **cognition**: dominant = `pattern_matcher` (39 of 40)
- **metabolism**: dominant = `voracious` (37 of 40)
- **lifespan**: dominant = `ancient` (39 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.