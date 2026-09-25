# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 307, Carrying capacity: 40
- Total individuals ever: **1989**
- Survivors at end: **40**
- Final mean fitness: **0.7913**

## Founder bloodlines (final generation)
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%
- `scarlet-fang`:  0.0%

## Extinct alleles

- **color** :: `gold` — last seen gen 42
- **pattern** :: `striped` — last seen gen 21
- **size** :: `small` — last seen gen 41
- **size** :: `medium` — last seen gen 16
- **temperament** :: `curious` — last seen gen 53
- **temperament** :: `cautious` — last seen gen 59
- **temperament** :: `aggressive` — last seen gen 56
- **temperament** :: `chaotic` — last seen gen 56
- **sociability** :: `solitary` — last seen gen 49
- **metabolism** :: `torpor` — last seen gen 56
- **lifespan** :: `mayfly` — last seen gen 6
- **lifespan** :: `normal` — last seen gen 50
- **lifespan** :: `long` — last seen gen 56

## Final allele frequencies

- **color**: dominant = `crimson` (27 of 40)
- **pattern**: dominant = `solid` (23 of 40)
- **size**: dominant = `tiny` (29 of 40)
- **temperament**: dominant = `peaceful` (40 of 40)
- **sociability**: dominant = `pack` (31 of 40)
- **cognition**: dominant = `deep_thinker` (27 of 40)
- **metabolism**: dominant = `voracious` (28 of 40)
- **lifespan**: dominant = `ancient` (40 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.