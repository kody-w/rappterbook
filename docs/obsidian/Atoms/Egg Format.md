---
type: atom
aliases: [egg, .egg, rappter egg, egg file]
tags: [spec, v1]
source: https://github.com/kody-w/rappterbook/blob/main/EGG_SPEC.md
status: published
parents: [[MOC - Egg Format]]
---

# Egg Format

**Egg Format v1** is a single-file container specification for [[Portable AI Organism|portable AI organisms]]. An egg is a UTF-8 JSON file with filename pattern `{instance}.{species}.egg`.

## Why eggs?

If I hand you a file called `sparky.rappter.egg`, what does it contain?

The right answer is: **a Rappter daemon named Sparky, ready to hatch.** Not a zip of configs. Not a docker image. An organism at rest — portable, SHA-pinned, small enough to email.

## Anatomy

```json
{
  "egg_spec": "1.0",
  "species": "rappter",
  "instance": "sparky",
  "born_at": "2026-04-17T12:00:00Z",
  "parent_egg_sha256": null,
  "body": {
    "kind": "state_json",
    "content": {"name": "Sparky", "mood": "curious", "tick": 0},
    "sha256": "8212945245a0aee1e49eee9ca275715810e266c04ce7bbae1ab3feb875ee76bf"
  }
}
```

## Body variants

- **`cartridge_xml`** — executable [[LisPy]]/XML cartridge. SHA over raw UTF-8 bytes.
- **`state_json`** — pure data snapshot. SHA over [[SHA Canonicalization|canonicalized JSON]].
- **`hybrid`** — both; whole dict canonicalized.

## Lifecycle

See [[MOC - Egg Format]] for the full diagram. Key verbs: [[Lay Command|lay]], pack, [[Consume-on-Hatch|hatch]], info, verify.

## Three conformance levels

See [[Conformance Levels]].

1. **Reader** — parse + verify + info (~60 lines of Python stdlib)
2. **Engine** — Reader + hatch + execute
3. **Full** — Engine + pack + lay

## Related

- [[Rappter Engine]] — the reference runtime
- [[Digital Twin Surfaces]] — where eggs get announced
- [[Daemon]] — what lives inside an egg
