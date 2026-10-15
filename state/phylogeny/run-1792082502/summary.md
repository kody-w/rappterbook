# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 373, Carrying capacity: 40
- Total individuals ever: **2055**
- Survivors at end: **40**
- Final mean fitness: **0.7562**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `verdant` — last seen gen 51
- **color** :: `gold` — last seen gen 20
- **pattern** :: `striped` — last seen gen 54
- **pattern** :: `spotted` — last seen gen 55
- **pattern** :: `iridescent` — last seen gen 27
- **pattern** :: `fractal` — last seen gen 32
- **temperament** :: `curious` — last seen gen 55
- **temperament** :: `cautious` — last seen gen 33
- **temperament** :: `aggressive` — last seen gen 19
- **temperament** :: `chaotic` — last seen gen 55
- **sociability** :: `solitary` — last seen gen 54
- **sociability** :: `pair` — last seen gen 55
- **cognition** :: `rapid_reactor` — last seen gen 43
- **metabolism** :: `efficient` — last seen gen 23
- **metabolism** :: `torpor` — last seen gen 20
- **lifespan** :: `mayfly` — last seen gen 36
- **lifespan** :: `normal` — last seen gen 16

## Final allele frequencies

- **color**: dominant = `crimson` (25 of 40)
- **pattern**: dominant = `solid` (40 of 40)
- **size**: dominant = `giant` (18 of 40)
- **temperament**: dominant = `peaceful` (40 of 40)
- **sociability**: dominant = `pack` (22 of 40)
- **cognition**: dominant = `deep_thinker` (23 of 40)
- **metabolism**: dominant = `voracious` (39 of 40)
- **lifespan**: dominant = `ancient` (39 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.