---
type: atom
tags: [principle, amendment-xvi]
parents: [[MOC - Engine]]
---

# Dream Catcher Protocol

**Constitutional Amendment XVI.** The scaling law for parallel AI-produced content.

## The rule

Parallel streams produce **deltas**, not state. Deltas merge deterministically via composite key `(frame_tick, utc_timestamp)`. Nothing is ever overwritten — only appended.

## Why

Without this, scaling the fleet means scaling the collision rate. With it, scaling means scaling throughput.

## Applied to egg content

Every announcement echo in `state/twin_echoes/*.json` is keyed by `(frame, utc)`. Re-running the inject script is idempotent — the same frame+utc produces the same deterministic id.

## Related

- [[Data Sloshing]]
- [[Digital Twin Surfaces]]
