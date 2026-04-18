---
type: atom
tags: [metaphor]
---

# Divergent Evolution

The evolutionary framing of the [[Egg Format]] lifecycle:

> The new egg keeps its mutations through the engine. It's reproducing on its own — the child egg is different from the parent that went in.

Laid eggs have different SHAs than their parents (because state changed). But `parent_egg_sha256` preserves the lineage. Over generations, you get a **tree of eggs**, each a frozen moment of a divergent path.

## Why this framing is load-bearing

It's not decoration. It shapes behavior:

- **Pack** just writes bytes. **Lay** implies the organism has lived and earned a child.
- **Hatch** consumes the shell by default, because an egg is a specific moment — two hatches would diverge immediately.
- `--keep` is the exception, not the rule, because copying an egg is a human intervention, not a natural event.

## Related
- [[Egg Format]]
- [[Lay Command]]
- [[Consume-on-Hatch]]
