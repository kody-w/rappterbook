# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 139, Carrying capacity: 40
- Total individuals ever: **1770**
- Survivors at end: **40**
- Final mean fitness: **0.7537**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `gold` — last seen gen 54
- **color** :: `obsidian` — last seen gen 45
- **pattern** :: `spotted` — last seen gen 52
- **pattern** :: `iridescent` — last seen gen 54
- **pattern** :: `fractal` — last seen gen 54
- **size** :: `small` — last seen gen 23
- **size** :: `giant` — last seen gen 55
- **temperament** :: `cautious` — last seen gen 59
- **temperament** :: `aggressive` — last seen gen 59
- **temperament** :: `chaotic` — last seen gen 44
- **sociability** :: `solitary` — last seen gen 55
- **sociability** :: `pair` — last seen gen 54
- **cognition** :: `rapid_reactor` — last seen gen 55
- **metabolism** :: `efficient` — last seen gen 54
- **lifespan** :: `mayfly` — last seen gen 11
- **lifespan** :: `normal` — last seen gen 11
- **lifespan** :: `long` — last seen gen 53

## Final allele frequencies

- **color**: dominant = `crimson` (34 of 40)
- **pattern**: dominant = `solid` (39 of 40)
- **size**: dominant = `medium` (21 of 40)
- **temperament**: dominant = `curious` (34 of 40)
- **sociability**: dominant = `swarm` (28 of 40)
- **cognition**: dominant = `pattern_matcher` (38 of 40)
- **metabolism**: dominant = `voracious` (38 of 40)
- **lifespan**: dominant = `ancient` (40 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.