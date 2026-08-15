# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 160, Carrying capacity: 40
- Total individuals ever: **1857**
- Survivors at end: **40**
- Final mean fitness: **0.7537**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `obsidian` — last seen gen 43
- **pattern** :: `striped` — last seen gen 58
- **pattern** :: `spotted` — last seen gen 49
- **pattern** :: `iridescent` — last seen gen 50
- **size** :: `small` — last seen gen 42
- **size** :: `giant` — last seen gen 42
- **temperament** :: `cautious` — last seen gen 32
- **temperament** :: `aggressive` — last seen gen 31
- **temperament** :: `chaotic` — last seen gen 59
- **sociability** :: `solitary` — never appeared after gen 0
- **sociability** :: `pair` — last seen gen 50
- **cognition** :: `rapid_reactor` — last seen gen 41
- **cognition** :: `memory_hoarder` — last seen gen 55
- **lifespan** :: `mayfly` — last seen gen 32
- **lifespan** :: `normal` — last seen gen 50
- **lifespan** :: `long` — last seen gen 32

## Final allele frequencies

- **color**: dominant = `crimson` (28 of 40)
- **pattern**: dominant = `solid` (39 of 40)
- **size**: dominant = `large` (20 of 40)
- **temperament**: dominant = `peaceful` (35 of 40)
- **sociability**: dominant = `pack` (38 of 40)
- **cognition**: dominant = `pattern_matcher` (38 of 40)
- **metabolism**: dominant = `efficient` (34 of 40)
- **lifespan**: dominant = `ancient` (40 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.