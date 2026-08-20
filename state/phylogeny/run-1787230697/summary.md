# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 178, Carrying capacity: 40
- Total individuals ever: **1721**
- Survivors at end: **40**
- Final mean fitness: **0.78**

## Founder bloodlines (final generation)
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `scarlet-fang`:  0.0%
- `gold-storm`:  0.0%

## Extinct alleles

- **color** :: `obsidian` — last seen gen 50
- **pattern** :: `fractal` — last seen gen 54
- **size** :: `medium` — last seen gen 46
- **temperament** :: `cautious` — last seen gen 59
- **temperament** :: `aggressive` — last seen gen 29
- **temperament** :: `chaotic` — last seen gen 55
- **sociability** :: `pair` — last seen gen 55
- **cognition** :: `rapid_reactor` — last seen gen 39
- **cognition** :: `memory_hoarder` — last seen gen 56
- **lifespan** :: `mayfly` — last seen gen 13
- **lifespan** :: `normal` — last seen gen 55

## Final allele frequencies

- **color**: dominant = `crimson` (33 of 40)
- **pattern**: dominant = `striped` (34 of 40)
- **size**: dominant = `tiny` (28 of 40)
- **temperament**: dominant = `curious` (30 of 40)
- **sociability**: dominant = `pack` (32 of 40)
- **cognition**: dominant = `pattern_matcher` (37 of 40)
- **metabolism**: dominant = `voracious` (31 of 40)
- **lifespan**: dominant = `ancient` (34 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.