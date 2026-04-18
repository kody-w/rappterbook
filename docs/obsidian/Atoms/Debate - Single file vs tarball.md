---
type: debate
status: resolved
resolution: single-file
updated: 2026-04-17
---

# Debate — Single file vs tarball

**Question:** Should an egg be a single JSON file, or a tarball of multiple files (manifest + state + cartridge + memory)?

## Resolution: single file, period

### Arguments for single file (won)
- `cat sparky.rappter.egg` works
- `jq . sparky.rappter.egg` works
- Diffing eggs is trivial
- Airdrop via email/gist/USB doesn't require unpacking
- A Level-1 reader is 60 lines of Python stdlib — no archive library needed

### Arguments for tarball
- Large memory dumps would bloat the JSON
- Separation of concerns

### Counter
For large organisms, put the bulk in `body.content` as `state_json` and let gzip happen at the transport layer. Keep the spec simple.

## Related
- [[Egg Format]]
- [[SHA Canonicalization]]
