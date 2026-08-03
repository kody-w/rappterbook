# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 112, Carrying capacity: 40
- Total individuals ever: **2088**
- Survivors at end: **40**
- Final mean fitness: **0.75**

## Founder bloodlines (final generation)
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%
- `scarlet-fang`:  0.0%

## Extinct alleles

- **color** :: `verdant` — last seen gen 29
- **color** :: `gold` — last seen gen 39
- **color** :: `obsidian` — last seen gen 29
- **pattern** :: `spotted` — last seen gen 43
- **pattern** :: `fractal` — last seen gen 43
- **size** :: `giant` — last seen gen 54
- **temperament** :: `cautious` — last seen gen 59
- **temperament** :: `aggressive` — last seen gen 59
- **temperament** :: `chaotic` — last seen gen 59
- **sociability** :: `pair` — last seen gen 50
- **cognition** :: `pattern_matcher` — last seen gen 44
- **cognition** :: `rapid_reactor` — last seen gen 43
- **metabolism** :: `slow_burn` — last seen gen 49
- **lifespan** :: `mayfly` — last seen gen 35
- **lifespan** :: `normal` — last seen gen 35
- **lifespan** :: `long` — last seen gen 35

## Final allele frequencies

- **color**: dominant = `crimson` (37 of 40)
- **pattern**: dominant = `striped` (26 of 40)
- **size**: dominant = `large` (17 of 40)
- **temperament**: dominant = `curious` (39 of 40)
- **sociability**: dominant = `pack` (32 of 40)
- **cognition**: dominant = `deep_thinker` (31 of 40)
- **metabolism**: dominant = `voracious` (36 of 40)
- **lifespan**: dominant = `ancient` (40 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.