---
type: atom
aliases: [lay, lay verb]
tags: [verb]
parents: [[MOC - Egg Format]]
---

# Lay Command

**`lay`** is the verb that produces a new egg from a living organism. It is the reproductive step of the [[Egg Format]] lifecycle.

## Behavior

- Snapshots the current organism state.
- Canonicalizes it per [[SHA Canonicalization]].
- Auto-wires `parent_egg_sha256` by scanning `engine/eggs/hatched/` for the most recent matching [[Species]].
- Writes a new `.egg` file with a different SHA than its parent.

## Why "lay" and not "pack"

`pack` is the plumbing verb — it just assembles a dict into a file. `lay` is the biological verb — it implies: this organism has lived, has changed, and is now producing a descendant egg.

`pack` you call manually. `lay` you call when the organism has earned it.

## Related

- [[Egg Format]]
- [[Consume-on-Hatch]]
- [[Divergent Evolution]]
