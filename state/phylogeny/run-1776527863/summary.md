# Egg Phylogeny — Run Summary

- Generations simulated: **30**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 100, Carrying capacity: 20
- Total individuals ever: **411**
- Survivors at end: **20**
- Final mean fitness: **0.75**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `azure` — last seen gen 12
- **color** :: `verdant` — last seen gen 24
- **color** :: `gold` — last seen gen 26
- **color** :: `obsidian` — last seen gen 25
- **pattern** :: `solid` — last seen gen 25
- **pattern** :: `fractal` — last seen gen 11
- **size** :: `tiny` — never appeared after gen 0
- **size** :: `small` — never appeared after gen 0
- **size** :: `medium` — last seen gen 9
- **size** :: `giant` — last seen gen 10
- **temperament** :: `curious` — last seen gen 9
- **temperament** :: `chaotic` — last seen gen 2
- **sociability** :: `solitary` — last seen gen 9
- **sociability** :: `pair` — last seen gen 9
- **sociability** :: `swarm` — last seen gen 12
- **cognition** :: `rapid_reactor` — last seen gen 25
- **metabolism** :: `efficient` — last seen gen 9
- **metabolism** :: `slow_burn` — last seen gen 4
- **metabolism** :: `torpor` — last seen gen 26
- **lifespan** :: `mayfly` — last seen gen 4
- **lifespan** :: `normal` — last seen gen 8
- **lifespan** :: `long` — last seen gen 28

## Final allele frequencies

- **color**: dominant = `crimson` (20 of 20)
- **pattern**: dominant = `striped` (17 of 20)
- **size**: dominant = `large` (20 of 20)
- **temperament**: dominant = `cautious` (14 of 20)
- **sociability**: dominant = `pack` (20 of 20)
- **cognition**: dominant = `pattern_matcher` (11 of 20)
- **metabolism**: dominant = `voracious` (20 of 20)
- **lifespan**: dominant = `ancient` (20 of 20)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.