# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 418, Carrying capacity: 40
- Total individuals ever: **1726**
- Survivors at end: **40**
- Final mean fitness: **0.75**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `azure` — last seen gen 15
- **color** :: `obsidian` — last seen gen 53
- **size** :: `tiny` — last seen gen 27
- **size** :: `giant` — last seen gen 14
- **temperament** :: `cautious` — last seen gen 54
- **temperament** :: `aggressive` — last seen gen 54
- **temperament** :: `chaotic` — last seen gen 39
- **sociability** :: `pair` — last seen gen 38
- **cognition** :: `rapid_reactor` — last seen gen 28
- **cognition** :: `memory_hoarder` — last seen gen 55
- **metabolism** :: `efficient` — last seen gen 28
- **metabolism** :: `slow_burn` — last seen gen 21
- **metabolism** :: `torpor` — last seen gen 22
- **lifespan** :: `mayfly` — last seen gen 11
- **lifespan** :: `normal` — last seen gen 55
- **lifespan** :: `long` — last seen gen 28

## Final allele frequencies

- **color**: dominant = `crimson` (32 of 40)
- **pattern**: dominant = `striped` (28 of 40)
- **size**: dominant = `large` (35 of 40)
- **temperament**: dominant = `curious` (20 of 40)
- **sociability**: dominant = `pack` (34 of 40)
- **cognition**: dominant = `pattern_matcher` (38 of 40)
- **metabolism**: dominant = `voracious` (40 of 40)
- **lifespan**: dominant = `ancient` (40 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.