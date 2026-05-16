---
type: atom
tags: [lifecycle]
parents: [[MOC - Egg Format]]
---

# Consume-on-Hatch

When an [[Egg Format|egg]] hatches, the shell is **consumed** — moved to `engine/eggs/hatched/{sha}.egg`.

The living organism now lives in the engine. The shell is no longer "the organism" — it is the *record* that this organism was once hatched here, at this SHA, from this parent.

## Why consume?

- **One-organism-one-shell** — an egg represents a specific moment; after hatching, that moment is past.
- **Lineage trace** — archived shells form the ancestral record, readable by [[Lay Command|lay]] to auto-wire parents.
- **Clean semantics** — two hatches of the same egg would diverge immediately; better to require explicit `--keep` for that case.

## Opt-out

`rappter hatch --keep sparky.rappter.egg` preserves the original for multi-recipient distribution.

## Related

- [[Egg Format]]
- [[Lay Command]]
- [[Hatching Contract]]
