# Egg Phylogeny — Run Summary

- Generations simulated: **60**
- Founders: scarlet-fang, azure-mind, verdant-vow, gold-storm
- Seed: 412, Carrying capacity: 40
- Total individuals ever: **1771**
- Survivors at end: **40**
- Final mean fitness: **0.76**

## Founder bloodlines (final generation)
- `azure-mind`: ██████████████████████████████ 100.0%
- `verdant-vow`: ██████████████████████████████ 100.0%
- `gold-storm`: ██████████████████████████████ 100.0%
- `scarlet-fang`:  0.0%

## Extinct alleles

- **color** :: `azure` — last seen gen 50
- **color** :: `gold` — last seen gen 47
- **pattern** :: `iridescent` — last seen gen 41
- **pattern** :: `fractal` — last seen gen 52
- **size** :: `tiny` — last seen gen 24
- **size** :: `small` — last seen gen 41
- **size** :: `giant` — last seen gen 59
- **temperament** :: `cautious` — last seen gen 36
- **temperament** :: `aggressive` — last seen gen 59
- **temperament** :: `chaotic` — last seen gen 59
- **sociability** :: `pair` — last seen gen 49
- **sociability** :: `swarm` — last seen gen 36
- **cognition** :: `rapid_reactor` — last seen gen 40
- **cognition** :: `memory_hoarder` — last seen gen 53
- **metabolism** :: `torpor` — last seen gen 57
- **lifespan** :: `mayfly` — last seen gen 9
- **lifespan** :: `normal` — last seen gen 59

## Final allele frequencies

- **color**: dominant = `crimson` (35 of 40)
- **pattern**: dominant = `striped` (29 of 40)
- **size**: dominant = `medium` (27 of 40)
- **temperament**: dominant = `peaceful` (23 of 40)
- **sociability**: dominant = `pack` (39 of 40)
- **cognition**: dominant = `pattern_matcher` (39 of 40)
- **metabolism**: dominant = `voracious` (34 of 40)
- **lifespan**: dominant = `ancient` (39 of 40)

## Merge function

Defined in `scripts/egg_phylogeny.py:merge_genomes`. Pure function of (parent_a_id, genome_a, parent_b_id, genome_b, generation). SHA-256 driven, 70% dominance bias, 4% mutation rate. Same inputs → same outputs.