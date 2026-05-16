---
type: atom
tags: [substrate]
---

# LisPy

A safe-eval Lisp dialect. S-expressions are both data AND executable code (homoiconic).

## Why LisPy, not Python

- **Safe eval** — no file I/O, no imports, no network. You can eval untrusted agent output.
- **Homoiconic** — data IS code, so one frame's output can be the next frame's program.
- **Protocol** — s-expressions serve as both data format and executable policy for federation.

## Related
- [[Cartridge]]
- [[Data Sloshing]]
- [[Turtles All The Way Down]]
