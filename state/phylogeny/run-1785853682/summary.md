# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 118, Carrying capacity: 40
- Total individuals ever: **1757**
- Survivors at end: **40**
- Final mean fitness: **0.7562**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`:  0.0%
- `gold-storm`:  0.0%

## Extinct alleles

- **color** :: `verdant` — last seen gen 55
- **color** :: `gold` — last seen gen 27
- **pattern** :: `spotted` — last seen gen 53
- **pattern** :: `fractal` — last seen gen 5
- **size** :: `medium` — last seen gen 22
- **size** :: `giant` — last seen gen 30
- **temperament** :: `cautious` — last seen gen 51
- **temperament** :: `aggressive` — last seen gen 30
- **temperament** :: `chaotic` — last seen gen 42
- **sociability** :: `solitary` — last seen gen 53
- **sociability** :: `pair` — last seen gen 50
- **cognition** :: `rapid_reactor` — last seen gen 41
- **metabolism** :: `efficient` — last seen gen 26
- **metabolism** :: `torpor` — last seen gen 51
- **lifespan** :: `mayfly` — last seen gen 6
- **lifespan** :: `normal` — last seen gen 22

## Final allele frequencies

- **color**: dominant = `crimson` (36 of 40)
- **pattern**: dominant = `solid` (34 of 40)
- **size**: dominant = `small` (23 of 40)
- **temperament**: dominant = `curious` (20 of 40)
- **sociability**: dominant = `pack` (39 of 40)
- **cognition**: dominant = `deep_thinker` (37 of 40)
- **metabolism**: dominant = `voracious` (39 of 40)
- **lifespan**: dominant = `ancient` (39 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.