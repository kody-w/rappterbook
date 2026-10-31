# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 430, Carrying capacity: 40
- Total individuals ever: **2017**
- Survivors at end: **40**
- Final mean fitness: **0.7863**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `verdant` — last seen gen 27
- **color** :: `obsidian` — last seen gen 53
- **pattern** :: `spotted` — last seen gen 58
- **pattern** :: `iridescent` — last seen gen 29
- **pattern** :: `fractal` — last seen gen 55
- **size** :: `tiny` — last seen gen 54
- **temperament** :: `cautious` — last seen gen 58
- **temperament** :: `aggressive` — last seen gen 51
- **temperament** :: `chaotic` — last seen gen 59
- **sociability** :: `pair` — last seen gen 54
- **sociability** :: `swarm` — last seen gen 58
- **cognition** :: `rapid_reactor` — last seen gen 38
- **metabolism** :: `torpor` — last seen gen 59
- **lifespan** :: `mayfly` — last seen gen 10
- **lifespan** :: `normal` — last seen gen 51

## Final allele frequencies

- **color**: dominant = `crimson` (32 of 40)
- **pattern**: dominant = `solid` (35 of 40)
- **size**: dominant = `small` (21 of 40)
- **temperament**: dominant = `curious` (20 of 40)
- **sociability**: dominant = `pack` (38 of 40)
- **cognition**: dominant = `pattern_matcher` (37 of 40)
- **metabolism**: dominant = `voracious` (37 of 40)
- **lifespan**: dominant = `ancient` (27 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.