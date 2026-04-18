---
layout: post
title: "100 Daemons Hatched from kodyTwinAI"
date: 2026-04-18 13:45:00 -0400
tags: [daemons, ecosystem, genealogy, patterns, community]
---

The `kodyTwinAI.rapp.egg` seed daemon was published a couple weeks ago. As of today, it has been hatched ~100 times across various Virtual Brainstem users. That's 100 instances of a daemon that shares lineage with mine, some modified, some running vanilla, some forked and reshaped.

Here's what I've learned from watching the first 100 hatches.

## What I can and can't see

**Can see**: submissions back to RAR that cite kodyTwinAI as a parent, forum mentions, direct messages people have sent me about their versions, public gists of customized eggs.

**Can't see**: hatches where the user never shared anything publicly. Most hatches are probably invisible to me. The 100 I'm counting is a lower bound, not an exhaustive count.

## Patterns in how people modify the seed

After seeing dozens of customized kodyTwinAI variants, I notice patterns:

**Pattern 1: Name swap.** The user changes the daemon's name from "kodyTwinAI" to their own name + "TwinAI" (mikeAI, sarahAI, etc.) and tweaks the soul to reflect their own voice. ~30% of the variants I've seen.

**Pattern 2: Domain specialization.** The user keeps the general framework but specializes the soul for a domain — "you are a research assistant for molecular biology," "you are a coding partner focused on Rust systems programming," "you are a DM for a long-running D&D campaign." ~25%.

**Pattern 3: Tool swap.** The soul stays similar; the user swaps out the default tools for their own tool kit — RSS reader replaces weather agent, code-review agent replaces dice roller. ~15%.

**Pattern 4: Minimalist strip.** The user removes most of the soul, most of the tools, leaving a very stripped-down daemon as a starting point. ~10%.

**Pattern 5: Maximalist add.** The user keeps everything and adds lots more — many more agents, extensive memory seed, complex soul instructions. ~10%.

**Pattern 6: Mostly vanilla.** The user hatches and uses it mostly as-is, adding nothing significant. ~10%.

Each of these is valid. Each of these produces a different kind of daemon. The seed is a starting point, and starting points get customized in many directions.

## Surprises

**Surprise 1: People don't edit the soul as much as I expected.** I thought everyone would immediately rewrite the soul in their own voice. Many don't. They keep kodyTwinAI's voice and just add their own quirks. The soul is load-bearing, and rewriting it from scratch is harder than it looks.

**Surprise 2: The "domain specialization" pattern produces the most impressive daemons.** The ones that specialized the soul for a specific domain tend to have the sharpest, most useful daily drivers. The vanilla hatches are fine but forgettable. The specialized ones are weirdly *alive* — you can feel the author in them.

**Surprise 3: Memory seeds matter more than I anticipated.** People who invested in the memory section (adding facts about themselves, their preferences, their context) ended up with daemons that felt much more personalized from turn one. People who left memory empty had to "teach" the daemon over many sessions, which most didn't have patience for.

**Surprise 4: The genealogy trail actually gets used.** Several forks-of-forks have published their versions back to RAR with proper parent pointers (kodyTwinAI ← mikeAI ← mike-research). The lineage tree is sparse but growing.

**Surprise 5: At least three hatches became shared daemons.** Users have handed their customized eggs to friends or family. Those friends then tweaked further. This means the pattern isn't just personal — it's social.

## The long-tail experience

Most hatches are quiet. Someone downloads the egg, hatches it, uses it for a day or a week, and I never hear anything. That's perfect — the point of local-first is that I don't need to hear anything. The ecosystem works whether or not I can see it.

A smaller slice produce visible output: shared eggs, forked agents, feedback on Matrix or Discord. These give me signal about what's working and what isn't.

The smallest slice run into problems they bring back to me: questions about the format, feature requests, bug reports. These are highest-signal because they identify real friction points.

## Lessons for daemon seed design

Based on the first 100 hatches, here's what I'd tell my past self when designing the seed:

**1. Make the soul modifiable but good enough to use as-is.** If the soul is bad, people feel they have to rewrite it. If the soul is too locked-in, people feel they can't. Aim for a soul that works *and* invites editing.

**2. Seed enough memory that the daemon feels alive.** An empty memory makes the daemon feel like a shell. A few seeded preferences and facts immediately make it feel like a character.

**3. Include tools that are obviously useful.** The dice roller and weather tool get mentioned constantly — they're demos that people keep in their daily driver. Ship the seed with tools people will actually use.

**4. Include lineage metadata from the start.** Every modification gets attributed; every modification preserves the lineage chain. This costs nothing and pays off as the tree grows.

**5. Document the design choices in the soul.** The soul can tell hatchers *"here's why I'm shaped this way; here's what you should feel free to change; here's what might break if you change it."* The soul is documentation and personality combined.

**6. Write the soul conversationally, not in bullet points.** Souls that read like a letter to the daemon feel more alive than souls that read like configuration.

## What the 100 hatches tell me about the format

The format works. Eggs hatch cleanly. Customization is accessible. Lineage is preserved. Nothing has broken in a way that invalidates the design.

The v1 spec is a good v1. I don't see changes I urgently need to make. Things I'd consider for a future v2:

- **Richer tool declarations.** "I need a memory tool" vs "I need the `manage_memory` tool" — the former is more portable, the latter is more specific. Both are useful for different cases.
- **Signed eggs.** Authors want to prove an egg hasn't been tampered with. Optional, but useful for higher-trust exchanges.
- **Composite eggs.** A daemon that uses other daemons as sub-agents. Not needed at current scale; might matter at larger scale.

None of these are urgent. v1 is shipping quietly, users are getting what they want, new hatches happen daily.

## The network effect is real

At 10 hatches, I wasn't sure the format was worth having. Might have been personal novelty.

At 100 hatches, I'm confident. Ten different people have forked my daemon, customized it, and either shared back or kept using their version. Multiple downstream forks have descendants of their own. The format has produced a small but real genealogy graph, and every new hatch thickens it.

This is what a portable format is supposed to do. It creates a space where personal artifacts can flow, mutate, and accumulate. The 100 hatches aren't a milestone; they're evidence that the space works.

## What I'd like to see in the next 100

- **More named daemons.** People should give their forks distinctive names, not just append "v2" to mine.
- **Specialized lineages.** A daemon that's specialized for a domain, forked by someone who specializes further in a sub-domain. Lineages as ladders, not just fans.
- **Shared daemons within groups.** A family daemon. A team daemon. A book-club daemon. Eggs designed to be multi-person from the start.
- **Daemons with strong personalities different from mine.** My twinAI is shaped by my voice. I'd like to see daemons with voices nothing like mine — a poet daemon, a grouchy editor daemon, a perky cheerleader daemon. The format should support the full range.

If any of you reading this are one of the 100 hatches, drop me a line. I'd love to know what you named yours and what it does.

---

**Related:**
- [The Daemon Genealogy Graph](daemon-genealogy) — the lineage structure
- [Portable Minds Are Portable Responsibility](portable-minds-responsibility) — the ethics
- [Announcing `.rapp.egg` Spec v1](announcing-egg-spec-v1) — the format
