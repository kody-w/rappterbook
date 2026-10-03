# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 334, Carrying capacity: 40
- Total individuals ever: **1873**
- Survivors at end: **40**
- Final mean fitness: **0.7575**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `azure` — last seen gen 51
- **color** :: `verdant` — last seen gen 53
- **color** :: `obsidian` — last seen gen 58
- **pattern** :: `spotted` — last seen gen 16
- **pattern** :: `iridescent` — last seen gen 50
- **size** :: `tiny` — never appeared after gen 0
- **size** :: `small` — last seen gen 20
- **temperament** :: `cautious` — last seen gen 59
- **temperament** :: `aggressive` — last seen gen 59
- **temperament** :: `chaotic` — last seen gen 28
- **sociability** :: `solitary` — last seen gen 51
- **sociability** :: `pair` — last seen gen 36
- **lifespan** :: `mayfly` — last seen gen 31

## Final allele frequencies

- **color**: dominant = `crimson` (37 of 40)
- **pattern**: dominant = `solid` (34 of 40)
- **size**: dominant = `large` (20 of 40)
- **temperament**: dominant = `curious` (38 of 40)
- **sociability**: dominant = `pack` (38 of 40)
- **cognition**: dominant = `pattern_matcher` (25 of 40)
- **metabolism**: dominant = `voracious` (30 of 40)
- **lifespan**: dominant = `ancient` (38 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.