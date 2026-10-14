# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 367, Carrying capacity: 40
- Total individuals ever: **1816**
- Survivors at end: **40**
- Final mean fitness: **0.7612**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `azure` — last seen gen 55
- **color** :: `obsidian` — last seen gen 54
- **pattern** :: `solid` — never appeared after gen 0
- **size** :: `small` — last seen gen 32
- **size** :: `giant` — last seen gen 43
- **temperament** :: `cautious` — last seen gen 59
- **temperament** :: `aggressive` — last seen gen 59
- **temperament** :: `chaotic` — last seen gen 59
- **sociability** :: `pair` — last seen gen 21
- **cognition** :: `deep_thinker` — last seen gen 52
- **cognition** :: `rapid_reactor` — last seen gen 32
- **lifespan** :: `mayfly` — last seen gen 30
- **lifespan** :: `normal` — last seen gen 5
- **lifespan** :: `long` — last seen gen 33

## Final allele frequencies

- **color**: dominant = `crimson` (34 of 40)
- **pattern**: dominant = `striped` (27 of 40)
- **size**: dominant = `tiny` (21 of 40)
- **temperament**: dominant = `curious` (36 of 40)
- **sociability**: dominant = `pack` (34 of 40)
- **cognition**: dominant = `pattern_matcher` (39 of 40)
- **metabolism**: dominant = `voracious` (29 of 40)
- **lifespan**: dominant = `ancient` (40 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.