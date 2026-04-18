---
type: debate
status: resolved
resolution: yes-by-default
updated: 2026-04-17
---

# Debate — Should hatch consume the shell

**Question:** When an egg hatches, should the original `.egg` file remain on disk?

## Resolution: consume by default, `--keep` opts out

### Arguments for consuming
- An egg represents a specific moment — two hatches would immediately diverge
- Lineage trace: archived shells (`engine/eggs/hatched/{sha}.egg`) form the ancestral record
- Clean semantics match the biological metaphor (a hatched egg shell is evidence, not an ongoing resource)

### Arguments for keeping
- Multi-recipient distribution — one egg, many hatches
- Accidents — consuming is irreversible without backups

### Compromise
Default: consume (archive to `engine/eggs/hatched/`). `--keep` preserves the original in place.

## Related
- [[Consume-on-Hatch]]
- [[Divergent Evolution]]
