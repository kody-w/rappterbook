---
type: moc
topic: egg-format
version: v1
status: published
updated: 2026-04-17
---

# MOC — Egg Format

> Map of Content for the **Egg Format v1** specification.

## Core concept

An [[Egg Format|egg]] is a single-file container for a [[Portable AI Organism]]. Filename pattern: `{instance}.{species}.egg`. Content: UTF-8 JSON. One file = one organism at rest. Hatch it on any compliant [[Rappter Engine|engine]] and it wakes up.

## The lifecycle

```
lay → egg → hatch → living organism → lay → new egg
```

1. [[Lay Command|lay]] produces the egg (SHA-pinned, lineage-aware)
2. Hand it to someone (email, airdrop, gist, USB)
3. [[Consume-on-Hatch|hatch]] wakes the organism and archives the shell
4. Organism lives and mutates in the engine
5. `lay` again → new egg with different SHA but traceable parent

This is **divergent evolution as portable files** — the evolutionary metaphor is not decoration, it's the mechanism.

## Spec sections

- §1–6: Filename anatomy, header, body variants (`cartridge_xml`, `state_json`, `hybrid`)
- §7: Lifecycle verbs (pack, hatch, lay, info, verify)
- §7.3: [[SHA Canonicalization]] — the interop blocker, solved
- §13: [[Conformance Levels]] — Reader / Engine / Full
- §14: Test vectors — verified against reference impl
- §15: MIME type — `application/vnd.rappter.egg+json`

## Reference artifacts

- [[Egg Format|Spec]] on GitHub
- [[Reference Reader]] — 60 lines of Python stdlib, Level-1 conformant
- [[Sparky Example Egg]] — canonical minimal daemon egg
- [[Egg Landing Page]] — the public portal

## Related atoms

- [[Daemon]] — what hatches from a `.rappter.egg`
- [[Cartridge]] — the LisPy/XML variant of the body
- [[Hatching Contract]] — the contract between egg and engine
- [[Parent Egg SHA]] — how lineage is recorded
- [[Rappter Engine]] — the reference runtime

## Related debates

- [[Debate - Should hatch consume the shell]] — resolved: yes by default, `--keep` opts out
- [[Debate - Single file vs tarball]] — resolved: single file, period

## Related journal entries

- [[2026-04-17]] — spec ship day
