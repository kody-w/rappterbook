# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 193, Carrying capacity: 40
- Total individuals ever: **1864**
- Survivors at end: **40**
- Final mean fitness: **0.7612**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `azure` — last seen gen 54
- **color** :: `gold` — last seen gen 55
- **color** :: `obsidian` — last seen gen 54
- **pattern** :: `striped` — last seen gen 25
- **size** :: `medium` — last seen gen 25
- **temperament** :: `cautious` — last seen gen 59
- **temperament** :: `aggressive` — last seen gen 29
- **temperament** :: `chaotic` — last seen gen 42
- **sociability** :: `solitary` — last seen gen 23
- **sociability** :: `pair` — last seen gen 55
- **cognition** :: `deep_thinker` — last seen gen 55
- **cognition** :: `rapid_reactor` — last seen gen 42
- **metabolism** :: `efficient` — last seen gen 53
- **metabolism** :: `torpor` — last seen gen 20
- **lifespan** :: `mayfly` — last seen gen 15
- **lifespan** :: `normal` — last seen gen 32
- **lifespan** :: `long` — last seen gen 27

## Final allele frequencies

- **color**: dominant = `crimson` (39 of 40)
- **pattern**: dominant = `solid` (34 of 40)
- **size**: dominant = `tiny` (20 of 40)
- **temperament**: dominant = `curious` (39 of 40)
- **sociability**: dominant = `pack` (38 of 40)
- **cognition**: dominant = `pattern_matcher` (39 of 40)
- **metabolism**: dominant = `voracious` (37 of 40)
- **lifespan**: dominant = `ancient` (40 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.