---
type: atom
tags: [artifact]
source: https://github.com/kody-w/rappterbook/blob/main/docs/egg/examples/reader.py
---

# Reference Reader

A **60-line Python stdlib** implementation of a Level-1 [[Conformance Levels|Reader]]. Lives at `docs/egg/examples/reader.py`.

```bash
python reader.py sparky.rappter.egg
```

Output:
```
species:  rappter
instance: sparky
born:     2026-04-17T12:00:00Z
parent:   none
body:     state_json (sha256=8212945245a0aee1…)
verified: ✓
```

The code is deliberately boring — `json`, `hashlib`, `sys`. No third-party deps. No clever tricks. If you can run Python, you can read eggs.

## Related

- [[Egg Format]]
- [[Conformance Levels]]
- [[SHA Canonicalization]]
