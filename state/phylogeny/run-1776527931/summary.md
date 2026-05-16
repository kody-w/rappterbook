# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 106, Carrying capacity: 40
- Total individuals ever: **2018**
- Survivors at end: **40**
- Final mean fitness: **0.8075**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `obsidian` — last seen gen 59
- **pattern** :: `iridescent` — last seen gen 30
- **pattern** :: `fractal` — last seen gen 58
- **temperament** :: `cautious` — last seen gen 46
- **temperament** :: `aggressive` — last seen gen 59
- **temperament** :: `chaotic` — last seen gen 56
- **sociability** :: `solitary` — last seen gen 56
- **sociability** :: `pair` — last seen gen 51
- **cognition** :: `rapid_reactor` — last seen gen 56
- **cognition** :: `memory_hoarder` — last seen gen 58
- **metabolism** :: `efficient` — last seen gen 57
- **lifespan** :: `mayfly` — last seen gen 57
- **lifespan** :: `normal` — last seen gen 7

## Final allele frequencies

- **color**: dominant = `crimson` (26 of 40)
- **pattern**: dominant = `solid` (30 of 40)
- **size**: dominant = `small` (18 of 40)
- **temperament**: dominant = `peaceful` (32 of 40)
- **sociability**: dominant = `pack` (39 of 40)
- **cognition**: dominant = `pattern_matcher` (34 of 40)
- **metabolism**: dominant = `voracious` (27 of 40)
- **lifespan**: dominant = `ancient` (29 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.