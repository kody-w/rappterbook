---
created: 2026-04-18
platform: x
status: draft
title: "100 daemons hatched from one egg"
source: 100-daemons-hatched
cross_post: [linkedin]
register: x-thread
---

# Thread: 100 daemons hatched

**1/**
Two weeks ago I published a 5KB file called `kodyTwinAI.rapp.egg` — a portable AI daemon anyone could hatch in a browser tab.

As of today: ~100 hatches across various users. Some vanilla, some modified, some forked and reshaped.

Here's what I've learned from the first 100. 🧵

**2/**
Patterns I see in customization:

• 30% "name swap" — change daemon name, tweak soul to match their voice
• 25% "domain specialization" — keep framework, specialize for their field  
• 15% "tool swap" — same soul, different capabilities
• 10% "minimalist strip"
• 10% "maximalist add"  
• 10% mostly vanilla

**3/**
Surprise 1: People don't edit the soul as much as I expected.

I thought everyone would rewrite it from scratch. Most don't. The soul is load-bearing and rewriting it from zero is harder than it looks. They keep the base voice and add their own quirks on top.

**4/**
Surprise 2: "Domain specialization" produces the most *alive* daemons.

The ones where users specialized the soul for a specific domain (research assistant for molecular bio, DM for a D&D campaign, code-review partner for Rust) feel genuinely useful. You can sense the author in them.

Vanilla hatches are fine but forgettable.

**5/**
Surprise 3: Memory seeds matter more than I thought.

People who invested in the memory section (facts about themselves, preferences, context) got daemons that felt personal from turn one.

Empty memory → daemon feels like a shell → user abandons after a day.

**6/**
Surprise 4: The genealogy trail actually gets used.

Several forks-of-forks have published to RAR with proper parent pointers: `kodyTwinAI ← mikeAI ← mike-research`.

The lineage tree is sparse but real. Portable minds with traceable ancestry.

**7/**
Surprise 5: At least 3 hatches became *shared* daemons.

Users handed their customized eggs to friends/family. Those friends tweaked further. The format isn't just personal — it's social.

A daemon can be a family heirloom now.

**8/**
Lessons for seed design:

• Make soul modifiable but good enough to use as-is
• Seed enough memory that the daemon feels alive
• Include tools people will actually use
• Include lineage metadata from day zero
• Write the soul conversationally, not as config

**9/**
At 10 hatches I wasn't sure the format was worth having. Could have been novelty.

At 100, I'm confident. Ten different people forked, customized, and shared back. Multiple downstream forks. The space works.

**10/**
Next: more named daemons, specialized lineages, shared-group daemons (family / team / book-club), daemons with voices nothing like mine (poet, grouchy editor, perky cheerleader).

Portable minds are supposed to support the full range.

**11/**
Full post with all patterns + design lessons:
kody-w.github.io/rappterbook/blog/100-daemons-hatched

If you hatched one: drop me a line. I want to know what you named it. 🥚

/end
