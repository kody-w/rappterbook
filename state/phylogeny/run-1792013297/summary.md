# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 370, Carrying capacity: 40
- Total individuals ever: **1888**
- Survivors at end: **40**
- Final mean fitness: **0.7525**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `gold` — last seen gen 57
- **color** :: `obsidian` — last seen gen 22
- **pattern** :: `spotted` — last seen gen 49
- **pattern** :: `fractal` — last seen gen 58
- **size** :: `tiny` — last seen gen 20
- **size** :: `giant` — last seen gen 55
- **temperament** :: `cautious` — last seen gen 59
- **temperament** :: `aggressive` — last seen gen 30
- **temperament** :: `chaotic` — last seen gen 51
- **sociability** :: `solitary` — last seen gen 55
- **sociability** :: `pair` — last seen gen 51
- **cognition** :: `rapid_reactor` — last seen gen 45
- **cognition** :: `memory_hoarder` — last seen gen 55
- **metabolism** :: `slow_burn` — last seen gen 54
- **lifespan** :: `mayfly` — last seen gen 31
- **lifespan** :: `normal` — last seen gen 19

## Final allele frequencies

- **color**: dominant = `crimson` (33 of 40)
- **pattern**: dominant = `striped` (37 of 40)
- **size**: dominant = `medium` (23 of 40)
- **temperament**: dominant = `curious` (29 of 40)
- **sociability**: dominant = `pack` (39 of 40)
- **cognition**: dominant = `pattern_matcher` (37 of 40)
- **metabolism**: dominant = `voracious` (32 of 40)
- **lifespan**: dominant = `ancient` (39 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.