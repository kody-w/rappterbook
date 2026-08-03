# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 115, Carrying capacity: 40
- Total individuals ever: **1904**
- Survivors at end: **40**
- Final mean fitness: **0.7562**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `azure` — last seen gen 53
- **color** :: `verdant` — last seen gen 53
- **color** :: `gold` — last seen gen 38
- **pattern** :: `striped` — last seen gen 53
- **pattern** :: `spotted` — last seen gen 49
- **pattern** :: `fractal` — last seen gen 53
- **size** :: `small` — last seen gen 41
- **size** :: `giant` — last seen gen 40
- **temperament** :: `curious` — last seen gen 13
- **temperament** :: `cautious` — last seen gen 38
- **temperament** :: `aggressive` — last seen gen 53
- **temperament** :: `chaotic` — last seen gen 53
- **sociability** :: `solitary` — last seen gen 49
- **metabolism** :: `efficient` — last seen gen 38
- **lifespan** :: `mayfly` — last seen gen 38
- **lifespan** :: `normal` — last seen gen 34

## Final allele frequencies

- **color**: dominant = `crimson` (35 of 40)
- **pattern**: dominant = `solid` (39 of 40)
- **size**: dominant = `large` (18 of 40)
- **temperament**: dominant = `peaceful` (40 of 40)
- **sociability**: dominant = `pack` (32 of 40)
- **cognition**: dominant = `deep_thinker` (36 of 40)
- **metabolism**: dominant = `voracious` (37 of 40)
- **lifespan**: dominant = `ancient` (39 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.