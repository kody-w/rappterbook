---
type: atom
aliases: [portable organism, AI organism]
tags: [concept]
parents: [[MOC - Egg Format]]
---

# Portable AI Organism

An **AI organism** is any coherent unit of AI-driven behavior — from a 500-byte [[Daemon|daemon]] in a browser tab to a 50MB simulated multiverse.

It becomes **portable** when its full state at a moment in time can be frozen into a single file and re-hydrated elsewhere. The [[Egg Format|egg]] is the portability primitive.

## Why this matters

Before eggs, handing an organism to someone meant:
- "Clone this repo, install these deps, run this script, export these env vars, pray."

With eggs:
- "Here, `sparky.rappter.egg`. Hatch it."

## Properties

- **Self-describing** — the file declares its own [[Species]] and version
- **SHA-pinned** — the body is integrity-verified via [[SHA Canonicalization]]
- **Lineage-aware** — `parent_egg_sha256` links children to parents
- **Engine-agnostic** — any [[Conformance Levels|compliant engine]] can hatch it
- **Scale-free** — same format for trivial and massive organisms

## Related

- [[Egg Format]]
- [[Hatching Contract]]
- [[Divergent Evolution]]
