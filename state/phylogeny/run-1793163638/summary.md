# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 421, Carrying capacity: 40
- Total individuals ever: **1784**
- Survivors at end: **40**
- Final mean fitness: **0.7575**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `verdant` — last seen gen 39
- **temperament** :: `cautious` — last seen gen 59
- **temperament** :: `aggressive` — last seen gen 55
- **temperament** :: `chaotic` — last seen gen 59
- **sociability** :: `pair` — last seen gen 50
- **cognition** :: `deep_thinker` — last seen gen 37
- **cognition** :: `rapid_reactor` — never appeared after gen 0
- **metabolism** :: `efficient` — last seen gen 28
- **lifespan** :: `mayfly` — last seen gen 1
- **lifespan** :: `normal` — last seen gen 50
- **lifespan** :: `long` — last seen gen 38

## Final allele frequencies

- **color**: dominant = `crimson` (34 of 40)
- **pattern**: dominant = `solid` (33 of 40)
- **size**: dominant = `medium` (26 of 40)
- **temperament**: dominant = `curious` (35 of 40)
- **sociability**: dominant = `pack` (34 of 40)
- **cognition**: dominant = `pattern_matcher` (39 of 40)
- **metabolism**: dominant = `voracious` (36 of 40)
- **lifespan**: dominant = `ancient` (40 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.