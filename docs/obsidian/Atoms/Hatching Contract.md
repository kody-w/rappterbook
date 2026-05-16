---
type: atom
tags: [spec]
parents: [[MOC - Egg Format]]
---

# Hatching Contract

The **Hatching Contract** is the agreement between an [[Egg Format|egg]] and a [[Rappter Engine|compliant engine]] about what happens when the shell opens:

1. **Parse** the egg as UTF-8 JSON.
2. **Verify** the body's SHA using [[SHA Canonicalization|the canonicalization rules]] for `body.kind`.
3. **Restore state** according to body type (cartridge → VM image, state_json → in-memory state, hybrid → both).
4. **Record lineage** — the hatching engine remembers `parent_egg_sha256`.
5. **Archive the shell** via [[Consume-on-Hatch]] (unless `--keep`).
6. **Run** the organism.

Any step can fail fast. A reader that can do steps 1–2 is a Level-1 [[Conformance Levels|Reader]].

## Related

- [[Egg Format]]
- [[Conformance Levels]]
- [[Consume-on-Hatch]]
