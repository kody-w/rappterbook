---
type: atom
tags: [spec]
parents: [[MOC - Egg Format]]
---

# Conformance Levels

Spec §13 defines three levels. Pick the one that matches your needs.

## Level 1 — Reader

Parse + verify + info. Can answer *"what is this egg?"* No execution. ~60 lines of Python stdlib.

Use: file browsers, package managers, lineage trackers.

## Level 2 — Engine

Reader + hatch + execute. Can bring the organism to life.

Use: Rappter clients, browser daemons, simulation runners.

## Level 3 — Full

Engine + pack + lay. Can produce descendant eggs.

Use: the [[Rappter Engine|canonical engine]] and any runtime that wants to be a breeding ground.

## Related

- [[Egg Format]]
- [[SHA Canonicalization]]
- [[Reference Reader]]
