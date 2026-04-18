# Egg Phylogeny — Run Summary

- Generations simulated: **50**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 42, Carrying capacity: 16
- Total individuals ever: **639**
- Survivors at end: **16**
- Final mean fitness: **0.675**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `gold` — last seen gen 5
- **color** :: `obsidian` — never appeared after gen 0
- **pattern** :: `striped` — never appeared after gen 0
- **pattern** :: `spotted` — last seen gen 43
- **pattern** :: `iridescent` — last seen gen 41
- **pattern** :: `fractal` — last seen gen 2
- **size** :: `small` — last seen gen 37
- **temperament** :: `aggressive` — last seen gen 43
- **temperament** :: `peaceful` — last seen gen 8
- **temperament** :: `chaotic` — last seen gen 42
- **sociability** :: `solitary` — last seen gen 29
- **cognition** :: `pattern_matcher` — last seen gen 44
- **cognition** :: `rapid_reactor` — last seen gen 43
- **metabolism** :: `efficient` — last seen gen 30
- **metabolism** :: `slow_burn` — last seen gen 26
- **metabolism** :: `torpor` — last seen gen 30
- **lifespan** :: `mayfly` — last seen gen 2
- **lifespan** :: `normal` — last seen gen 9
- **lifespan** :: `long` — last seen gen 19

## Final allele frequencies

- **color**: dominant = `crimson` (12 of 16)
- **pattern**: dominant = `solid` (16 of 16)
- **size**: dominant = `tiny` (8 of 16)
- **temperament**: dominant = `curious` (11 of 16)
- **sociability**: dominant = `pair` (8 of 16)
- **cognition**: dominant = `memory_hoarder` (8 of 16)
- **metabolism**: dominant = `voracious` (16 of 16)
- **lifespan**: dominant = `ancient` (16 of 16)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.