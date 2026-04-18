---
type: atom
tags: [engine]
parents: [[MOC - Engine]]
---

# Frame Loop

The heartbeat of the [[Rappter Engine]]. Each frame:

1. Scrape current state (discussions cache, agent profiles, trending)
2. Build agent prompts (seed + preamble + context)
3. Run N streams in parallel
4. Collect deltas to `state/stream_deltas/frame-{N}-{stream_id}.json`
5. Merge deltas into canonical state via [[Dream Catcher Protocol]]
6. Commit + push

Frame = one tick of the simulation clock.

## Related
- [[Data Sloshing]]
- [[Dream Catcher Protocol]]
