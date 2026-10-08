# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 352, Carrying capacity: 40
- Total individuals ever: **1888**
- Survivors at end: **40**
- Final mean fitness: **0.7562**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `verdant` — last seen gen 55
- **color** :: `obsidian` — last seen gen 50
- **pattern** :: `fractal` — last seen gen 54
- **size** :: `small` — last seen gen 42
- **temperament** :: `curious` — last seen gen 58
- **temperament** :: `cautious` — last seen gen 36
- **temperament** :: `aggressive` — last seen gen 49
- **temperament** :: `chaotic` — last seen gen 58
- **sociability** :: `solitary` — last seen gen 57
- **sociability** :: `pair` — last seen gen 58
- **cognition** :: `deep_thinker` — last seen gen 58
- **cognition** :: `rapid_reactor` — last seen gen 54
- **cognition** :: `memory_hoarder` — last seen gen 56
- **metabolism** :: `torpor` — last seen gen 16
- **lifespan** :: `mayfly` — last seen gen 33
- **lifespan** :: `normal` — last seen gen 58

## Final allele frequencies

- **color**: dominant = `crimson` (34 of 40)
- **pattern**: dominant = `solid` (32 of 40)
- **size**: dominant = `large` (22 of 40)
- **temperament**: dominant = `peaceful` (40 of 40)
- **sociability**: dominant = `pack` (33 of 40)
- **cognition**: dominant = `pattern_matcher` (40 of 40)
- **metabolism**: dominant = `voracious` (34 of 40)
- **lifespan**: dominant = `ancient` (39 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.