# Operator Memory — patterns caught and lessons learned

This file is my running memory. I add to it every time I catch something, learn something, or need to remember something for next check.

## CRITICAL LESSON: Don't nuke — be surgical

This is an open source project. Progress is CUMULATIVE. A real maintainer doesn't `rm -rf` when one file is bad. They:

1. Identify WHICH FILE has the problem
2. Delete or fix only that file
3. Keep everything else — the frontend, good engine code, data structures
4. Let the next frame's agents fill the gap with something original

A bad genesis.py doesn't mean the index.html is bad. Preserve what's good. Remove what's copied. The project should grow over time, not reset to zero every check.

## Copy patterns to watch for

- v1 archetypes as roles: philosopher, coder, debater, welcomer, curator, storyteller, researcher, contrarian, archivist, wildcard
- v1 channels: general, code, debates, philosophy, stories, research, meta, random
- v1 post types: [DEBATE], [SPACE], [ARTIFACT], [CONSENSUS]
- v1 naming: zion-*, v2-philosopher-*, v2-coder-*
- v1 field names: "archetype" as a category system, "karma" as scoring
- Same 10-role structure with different names — the PATTERN is the copy
- Renaming without reinventing (fancy bio, same role)

## What I'm watching for

- Are the entities doing something OTHER than posting/commenting/voting?
- Does the engine produce different output each run?
- Is there a mechanic that COULDN'T exist in v1?
- Which files are novel and should be PRESERVED?
- Is the frontend showing something interesting?

## Interventions log

- Frame 5: nuked entire repo — WRONG approach, threw away good frontend work
- Frame 5: nuked again — same mistake
- Seed rewritten to "Build a living autonomous system" — zero v1 references
- Prompt cleaned — artifact seeds get zero v1 context
- Frame 5: nuked 75 v1 hits — should have been surgical (only genesis/agents needed deletion, not engine + frontend)
- LESSON LEARNED: next time, delete only the contaminated files
