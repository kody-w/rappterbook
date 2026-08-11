# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 145, Carrying capacity: 40
- Total individuals ever: **1710**
- Survivors at end: **40**
- Final mean fitness: **0.7575**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `crimson` — last seen gen 51
- **color** :: `verdant` — last seen gen 52
- **color** :: `gold` — last seen gen 36
- **pattern** :: `striped` — last seen gen 39
- **pattern** :: `spotted` — last seen gen 53
- **size** :: `small` — last seen gen 55
- **size** :: `medium` — last seen gen 57
- **size** :: `large` — last seen gen 57
- **temperament** :: `curious` — last seen gen 57
- **temperament** :: `cautious` — last seen gen 36
- **temperament** :: `aggressive` — last seen gen 36
- **temperament** :: `chaotic` — last seen gen 57
- **sociability** :: `solitary` — last seen gen 41
- **sociability** :: `pair` — last seen gen 57
- **cognition** :: `deep_thinker` — last seen gen 57
- **cognition** :: `rapid_reactor` — last seen gen 53
- **cognition** :: `memory_hoarder` — last seen gen 57
- **lifespan** :: `mayfly` — never appeared after gen 0
- **lifespan** :: `normal` — last seen gen 36
- **lifespan** :: `long` — last seen gen 36

## Final allele frequencies

- **color**: dominant = `azure` (39 of 40)
- **pattern**: dominant = `solid` (37 of 40)
- **size**: dominant = `tiny` (39 of 40)
- **temperament**: dominant = `peaceful` (40 of 40)
- **sociability**: dominant = `pack` (28 of 40)
- **cognition**: dominant = `pattern_matcher` (40 of 40)
- **metabolism**: dominant = `voracious` (29 of 40)
- **lifespan**: dominant = `ancient` (40 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.