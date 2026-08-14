# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 154, Carrying capacity: 40
- Total individuals ever: **1948**
- Survivors at end: **40**
- Final mean fitness: **0.7712**

## Founder bloodlines (final generation)
- `scarlet-fang`: ██████████████████████████████ 100.0%
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%

## Extinct alleles

- **color** :: `azure` — last seen gen 58
- **color** :: `verdant` — last seen gen 55
- **color** :: `obsidian` — last seen gen 55
- **pattern** :: `iridescent` — last seen gen 55
- **temperament** :: `cautious` — last seen gen 31
- **temperament** :: `aggressive` — last seen gen 31
- **temperament** :: `chaotic` — last seen gen 55
- **sociability** :: `solitary` — last seen gen 49
- **sociability** :: `pair` — last seen gen 18
- **sociability** :: `swarm` — last seen gen 58
- **cognition** :: `rapid_reactor` — last seen gen 53
- **cognition** :: `memory_hoarder` — last seen gen 54
- **metabolism** :: `torpor` — last seen gen 59
- **lifespan** :: `mayfly` — last seen gen 12
- **lifespan** :: `normal` — last seen gen 59

## Final allele frequencies

- **color**: dominant = `crimson` (39 of 40)
- **pattern**: dominant = `solid` (22 of 40)
- **size**: dominant = `tiny` (19 of 40)
- **temperament**: dominant = `peaceful` (37 of 40)
- **sociability**: dominant = `pack` (40 of 40)
- **cognition**: dominant = `pattern_matcher` (37 of 40)
- **metabolism**: dominant = `voracious` (34 of 40)
- **lifespan**: dominant = `ancient` (39 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.