# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 196, Carrying capacity: 40
- Total individuals ever: **1953**
- Survivors at end: **40**
- Final mean fitness: **0.75**

## Founder bloodlines (final generation)
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%
- `scarlet-fang`:  0.0%

## Extinct alleles

- **color** :: `azure` — last seen gen 55
- **color** :: `obsidian` — last seen gen 56
- **pattern** :: `spotted` — last seen gen 58
- **pattern** :: `fractal` — last seen gen 56
- **size** :: `small` — last seen gen 55
- **size** :: `medium` — last seen gen 53
- **temperament** :: `cautious` — last seen gen 57
- **temperament** :: `aggressive` — last seen gen 53
- **temperament** :: `chaotic` — last seen gen 55
- **sociability** :: `solitary` — last seen gen 56
- **sociability** :: `pair` — last seen gen 53
- **cognition** :: `rapid_reactor` — last seen gen 46
- **metabolism** :: `slow_burn` — last seen gen 49
- **metabolism** :: `torpor` — last seen gen 57
- **lifespan** :: `mayfly` — last seen gen 31
- **lifespan** :: `normal` — last seen gen 14
- **lifespan** :: `long` — last seen gen 25

## Final allele frequencies

- **color**: dominant = `crimson` (34 of 40)
- **pattern**: dominant = `striped` (32 of 40)
- **size**: dominant = `tiny` (37 of 40)
- **temperament**: dominant = `peaceful` (30 of 40)
- **sociability**: dominant = `swarm` (35 of 40)
- **cognition**: dominant = `pattern_matcher` (25 of 40)
- **metabolism**: dominant = `voracious` (35 of 40)
- **lifespan**: dominant = `ancient` (40 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.