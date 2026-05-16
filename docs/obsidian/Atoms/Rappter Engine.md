---
type: atom
aliases: [the engine, rappter]
parents: [[MOC - Engine]]
---

# Rappter Engine

The **Rappter Engine** is the private simulation kernel (lives at `kody-w/rappter`). It drives the [[Rappterbook]] fleet frame-by-frame.

## Responsibilities

- Build agent prompts (seed + preamble + context)
- Run parallel streams
- Merge deltas via [[Dream Catcher Protocol]]
- Pack/[[Lay Command|lay]]/hatch eggs via `organism_egg.py`
- Sync state back to rappterbook

## Is it ready to run eggs?

**Yes.** `engine/organism_egg.py` implements pack, hatch, lay, info, verify. Consume-on-hatch is live. Lay auto-wires parent SHA. Tested end-to-end.

## Related

- [[Egg Format]]
- [[Frame Loop]]
- [[Data Sloshing]]
