# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 226, Carrying capacity: 40
- Total individuals ever: **1850**
- Survivors at end: **40**
- Final mean fitness: **0.7575**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `verdant` — last seen gen 47
- **color** :: `obsidian` — last seen gen 51
- **pattern** :: `striped` — last seen gen 22
- **pattern** :: `spotted` — last seen gen 34
- **pattern** :: `iridescent` — last seen gen 54
- **size** :: `tiny` — last seen gen 42
- **temperament** :: `cautious` — last seen gen 59
- **temperament** :: `aggressive` — last seen gen 50
- **temperament** :: `peaceful` — last seen gen 54
- **temperament** :: `chaotic` — last seen gen 59
- **sociability** :: `pair` — last seen gen 54
- **cognition** :: `deep_thinker` — last seen gen 53
- **cognition** :: `rapid_reactor` — last seen gen 30
- **cognition** :: `memory_hoarder` — last seen gen 54
- **metabolism** :: `slow_burn` — last seen gen 30
- **lifespan** :: `mayfly` — never appeared after gen 0
- **lifespan** :: `normal` — last seen gen 54

## Final allele frequencies

- **color**: dominant = `azure` (29 of 40)
- **pattern**: dominant = `solid` (39 of 40)
- **size**: dominant = `small` (31 of 40)
- **temperament**: dominant = `curious` (40 of 40)
- **sociability**: dominant = `pack` (23 of 40)
- **cognition**: dominant = `pattern_matcher` (40 of 40)
- **metabolism**: dominant = `efficient` (25 of 40)
- **lifespan**: dominant = `ancient` (37 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.