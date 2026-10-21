# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 394, Carrying capacity: 40
- Total individuals ever: **1810**
- Survivors at end: **40**
- Final mean fitness: **0.78**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `azure` — last seen gen 32
- **color** :: `verdant` — last seen gen 49
- **color** :: `gold` — last seen gen 53
- **color** :: `obsidian` — last seen gen 41
- **pattern** :: `striped` — last seen gen 44
- **pattern** :: `spotted` — last seen gen 13
- **pattern** :: `iridescent` — last seen gen 52
- **pattern** :: `fractal` — last seen gen 53
- **size** :: `tiny` — last seen gen 28
- **temperament** :: `cautious` — last seen gen 59
- **temperament** :: `aggressive` — last seen gen 35
- **sociability** :: `solitary` — last seen gen 6
- **cognition** :: `rapid_reactor` — last seen gen 51
- **cognition** :: `memory_hoarder` — last seen gen 54
- **metabolism** :: `efficient` — last seen gen 49
- **metabolism** :: `torpor` — last seen gen 24
- **lifespan** :: `mayfly` — last seen gen 37
- **lifespan** :: `normal` — last seen gen 50
- **lifespan** :: `long` — last seen gen 36

## Final allele frequencies

- **color**: dominant = `crimson` (40 of 40)
- **pattern**: dominant = `solid` (40 of 40)
- **size**: dominant = `medium` (23 of 40)
- **temperament**: dominant = `curious` (30 of 40)
- **sociability**: dominant = `pack` (34 of 40)
- **cognition**: dominant = `pattern_matcher` (39 of 40)
- **metabolism**: dominant = `voracious` (30 of 40)
- **lifespan**: dominant = `ancient` (40 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.