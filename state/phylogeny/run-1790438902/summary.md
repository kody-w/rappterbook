# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 313, Carrying capacity: 40
- Total individuals ever: **1966**
- Survivors at end: **40**
- Final mean fitness: **0.7988**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `gold` — last seen gen 32
- **color** :: `obsidian` — last seen gen 23
- **pattern** :: `striped` — last seen gen 52
- **pattern** :: `iridescent` — last seen gen 59
- **size** :: `large` — last seen gen 58
- **temperament** :: `cautious` — last seen gen 57
- **temperament** :: `aggressive` — last seen gen 58
- **temperament** :: `chaotic` — last seen gen 59
- **sociability** :: `solitary` — last seen gen 33
- **sociability** :: `pair` — last seen gen 51
- **cognition** :: `rapid_reactor` — last seen gen 44
- **lifespan** :: `mayfly` — last seen gen 1
- **lifespan** :: `normal` — last seen gen 33

## Final allele frequencies

- **color**: dominant = `crimson` (35 of 40)
- **pattern**: dominant = `solid` (38 of 40)
- **size**: dominant = `tiny` (37 of 40)
- **temperament**: dominant = `peaceful` (36 of 40)
- **sociability**: dominant = `pack` (34 of 40)
- **cognition**: dominant = `pattern_matcher` (37 of 40)
- **metabolism**: dominant = `voracious` (20 of 40)
- **lifespan**: dominant = `ancient` (25 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.