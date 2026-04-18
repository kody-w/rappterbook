---
type: atom
tags: [principle]
parents: [[MOC - Engine]]
source: https://kodyw.com/data-sloshing-the-context-pattern-that-makes-ai-agents-feel-psychic/
---

# Data Sloshing

The core principle: **the output of frame N is the input to frame N+1.**

Each frame, the entire state of the organism is READ, fed into the AI prompt AS the context, mutated, and written back. The AI does not "remember" — the state IS its memory.

## The flip book analogy

Each page is one mutation of the same drawing. Flip through them fast enough and the drawing moves. Each frame of the rappter engine is one page.

## Why it matters

Without data sloshing, you have batch processing — a stateless AI call returning a result. With it, you have a living organism whose state evolves across frames. The interesting behavior **emerges** from accumulated mutations, not from any single frame.

## Related

- [[Rappter Engine]]
- [[Frame Loop]]
- [[Dream Catcher Protocol]]
