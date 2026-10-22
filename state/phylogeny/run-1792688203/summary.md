# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 400, Carrying capacity: 40
- Total individuals ever: **2005**
- Survivors at end: **40**
- Final mean fitness: **0.755**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `azure` — last seen gen 30
- **color** :: `verdant` — last seen gen 51
- **color** :: `gold` — last seen gen 16
- **color** :: `obsidian` — last seen gen 28
- **pattern** :: `spotted` — last seen gen 49
- **pattern** :: `iridescent` — last seen gen 40
- **size** :: `medium` — last seen gen 16
- **temperament** :: `cautious` — last seen gen 31
- **temperament** :: `aggressive` — last seen gen 59
- **temperament** :: `peaceful` — last seen gen 14
- **temperament** :: `chaotic` — last seen gen 59
- **sociability** :: `solitary` — last seen gen 53
- **sociability** :: `pair` — last seen gen 53
- **cognition** :: `rapid_reactor` — last seen gen 40
- **metabolism** :: `slow_burn` — last seen gen 16
- **metabolism** :: `torpor` — last seen gen 23
- **lifespan** :: `mayfly` — last seen gen 3
- **lifespan** :: `normal` — last seen gen 31

## Final allele frequencies

- **color**: dominant = `crimson` (40 of 40)
- **pattern**: dominant = `solid` (29 of 40)
- **size**: dominant = `small` (19 of 40)
- **temperament**: dominant = `curious` (40 of 40)
- **sociability**: dominant = `pack` (35 of 40)
- **cognition**: dominant = `pattern_matcher` (18 of 40)
- **metabolism**: dominant = `voracious` (39 of 40)
- **lifespan**: dominant = `ancient` (38 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.