# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 280, Carrying capacity: 40
- Total individuals ever: **1920**
- Survivors at end: **40**
- Final mean fitness: **0.7562**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `crimson` — last seen gen 19
- **color** :: `obsidian` — last seen gen 41
- **pattern** :: `fractal` — last seen gen 59
- **size** :: `small` — last seen gen 56
- **size** :: `giant` — last seen gen 13
- **temperament** :: `curious` — last seen gen 58
- **temperament** :: `cautious` — last seen gen 34
- **temperament** :: `aggressive` — last seen gen 56
- **temperament** :: `chaotic` — last seen gen 56
- **sociability** :: `solitary` — last seen gen 49
- **sociability** :: `pair` — last seen gen 39
- **sociability** :: `swarm` — last seen gen 53
- **cognition** :: `deep_thinker` — last seen gen 58
- **cognition** :: `rapid_reactor` — last seen gen 42
- **cognition** :: `memory_hoarder` — last seen gen 58
- **metabolism** :: `efficient` — last seen gen 26
- **lifespan** :: `mayfly` — never appeared after gen 0
- **lifespan** :: `normal` — last seen gen 6

## Final allele frequencies

- **color**: dominant = `azure` (33 of 40)
- **pattern**: dominant = `solid` (29 of 40)
- **size**: dominant = `medium` (32 of 40)
- **temperament**: dominant = `peaceful` (40 of 40)
- **sociability**: dominant = `pack` (40 of 40)
- **cognition**: dominant = `pattern_matcher` (40 of 40)
- **metabolism**: dominant = `voracious` (34 of 40)
- **lifespan**: dominant = `ancient` (39 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.