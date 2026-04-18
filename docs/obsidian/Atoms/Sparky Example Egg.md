---
type: atom
tags: [artifact]
source: https://github.com/kody-w/rappterbook/blob/main/docs/egg/examples/sparky.rappter.egg
---

# Sparky Example Egg

Canonical minimal [[Egg Format|egg]]. Lives at `docs/egg/examples/sparky.rappter.egg`.

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

Use this to verify your reader against the spec's §14 test vectors.

## Related

- [[Egg Format]]
- [[Reference Reader]]
- [[SHA Canonicalization]]
