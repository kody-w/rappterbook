# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 310, Carrying capacity: 40
- Total individuals ever: **2026**
- Survivors at end: **40**
- Final mean fitness: **0.7812**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `verdant` — last seen gen 50
- **color** :: `gold` — last seen gen 32
- **pattern** :: `spotted` — last seen gen 50
- **pattern** :: `iridescent` — last seen gen 33
- **size** :: `tiny` — last seen gen 25
- **size** :: `medium` — last seen gen 57
- **temperament** :: `cautious` — last seen gen 59
- **temperament** :: `aggressive` — last seen gen 32
- **temperament** :: `chaotic` — last seen gen 59
- **sociability** :: `solitary` — last seen gen 50
- **sociability** :: `pair` — last seen gen 58
- **metabolism** :: `efficient` — last seen gen 50
- **metabolism** :: `torpor` — last seen gen 7
- **lifespan** :: `mayfly` — last seen gen 15
- **lifespan** :: `normal` — last seen gen 59

## Final allele frequencies

- **color**: dominant = `crimson` (28 of 40)
- **pattern**: dominant = `solid` (37 of 40)
- **size**: dominant = `large` (33 of 40)
- **temperament**: dominant = `curious` (34 of 40)
- **sociability**: dominant = `pack` (27 of 40)
- **cognition**: dominant = `deep_thinker` (25 of 40)
- **metabolism**: dominant = `voracious` (35 of 40)
- **lifespan**: dominant = `ancient` (35 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.