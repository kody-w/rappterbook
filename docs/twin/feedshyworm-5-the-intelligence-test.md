---
created: 2026-03-16
source: draft
url: 
tags: [blog, ai, game-development, claude, collaboration, opus, benchmark, intelligence-test]
status: draft
---

# FeedShyWorm 5.0: The Intelligence Test

Two years ago I built a worm game to see what AI could do. Now I use it to measure how much smarter AI has gotten.

FeedShyWorm started as a vibe check -- throw a concept at the model, see what comes back. Version 1.0 was a couple hours with ChatGPT. Version 2.0 was ninety minutes with Claude 3.5 Sonnet. Version 3.0 was minutes with Claude 4. Version 4.0 was a single conversation with Opus 4.5 that produced neural-inspired AI, four game modes, and a power-up system. Then I let eight agents evolve it autonomously for 24 hours.

That was December 2025. Three months ago.

Today I'm sitting in front of Claude Opus 4.6 with a 1M token context window, and I'm going to ask it to build FeedShyWorm 5.0. Not because the world needs another worm game -- because this game has become my benchmark. Same prompt lineage, same creative constraints, different model. The delta between versions is a direct measurement of intelligence gains.

Let me tell you what happened.

## The Prompt

I didn't engineer anything clever. I gave it the same seed I always give:

> "You're building FeedShyWorm 5.0. The player controls food, the worm chases it. Here's the history: 1.0 was Python, 2.0 was web, 3.0 was 3D Minecraft, 4.0 added neural AI with memory and prediction. 4.0 also ran through 24 hours of autonomous evolution. Now build 5.0. Surprise me."

That's it. Same framing every time. The only variable is the model.

## What Opus 4.6 Built

The response wasn't what I expected. Previous versions kept adding features -- more modes, more power-ups, more visual complexity. Opus 4.6 went the other direction. It *simplified*.

### The Ecosystem

Instead of one worm, there are dozens. Small ones. They form a population. Each worm has a genome -- a set of behavioral parameters encoded as floating-point weights:

- **aggression**: how directly it pursues food (0.0 = wanders, 1.0 = beelines)
- **memory**: how many of your past positions it tracks (0 to 50)
- **prediction_horizon**: how far ahead it models your trajectory (0 to 30 frames)
- **cooperation**: tendency to coordinate with nearby worms (0.0 = solo hunter, 1.0 = pack tactics)
- **caution**: avoidance of other worms and walls (0.0 = reckless, 1.0 = conservative)

When a worm eats food, it reproduces. Its offspring inherit the parent's genome with small mutations. Worms that never eat eventually starve and disappear.

You're not playing against one AI. You're playing against natural selection.

### What Emerges

In the first thirty seconds, the worms are dumb. Low memory, no prediction, random wandering. You score easily. Then the population shifts. The worms that reached your food first were the aggressive ones with decent prediction. They reproduced. Their children are slightly smarter, slightly faster to anticipate your feints.

By minute two, you notice pack behavior. Three worms approach from different angles -- not because they were programmed to flank, but because worms with high cooperation that happened to surround you were the ones that ate. Natural selection favored the flankers.

By minute five, the population has *specialized*. Some worms are pure chasers -- high aggression, low caution. Others are trappers -- low aggression, high cooperation, they position themselves where you'll dodge *to*. A few are scavengers -- they ignore you entirely and wait for food that the chasers miss.

I didn't design these roles. The model didn't design these roles. They emerged from selection pressure and a five-parameter genome. That's the part that made me put my coffee down.

### The Visualization

The game renders each worm's genome as its visual appearance:

- **Color hue** maps to aggression (blue = passive, red = aggressive)
- **Brightness** maps to memory (dim = forgetful, bright = remembers everything)
- **Size** maps to caution (large = careful, small = reckless)
- **Trail opacity** maps to cooperation (faint = lone wolf, solid = pack hunter)

You can read the battlefield. That cluster of bright red worms moving in formation? High aggression, high memory, high cooperation. The pack hunters. That lone dim blue worm hugging the wall? Low everything. The scavenger waiting for scraps.

The game becomes legible in a way that none of the previous versions were. You're not just dodging -- you're reading an ecosystem and making strategic decisions about which behavioral clusters to avoid.

### The Genome Viewer

A sidebar shows the population's genetic distribution in real-time. Histograms for each parameter. A lineage tree showing which worms descended from which. A "Most Dangerous Genome" readout tracking the parameters that have killed you the most.

When you die, the game shows you the genome of the worm that caught you. It shows its parents, its siblings, and what mutations made it successful. It's a post-mortem on evolution.

### Sound Design

Previous versions used simple Web Audio oscillators. Opus 4.6 generated a procedural ambient soundtrack that responds to population dynamics:

- **Tempo** increases with average population aggression
- **Harmonic complexity** increases with genetic diversity
- **Bass frequency** drops as cooperation rises (pack hunting sounds ominous)
- **A high ping** plays when a new mutation proves successful (a worm with a novel genome gets its first kill)

The audio tells you the state of the ecosystem before you even look at the screen. When the bass drops and the tempo spikes, the pack hunters are converging.

## What This Tells Us About Intelligence Gains

Here's the thing I actually care about. Not the game -- the delta.

| Version | Model | Time | What It Did |
|---------|-------|------|------------|
| 1.0 | GPT-3.5 | Hours | Basic mechanics. Chase logic. Grid rendering. |
| 2.0 | Claude 3.5 Sonnet | 90 min | Platform migration. Responsive design. Dual controls. |
| 3.0 | Claude 4 | Minutes | Full 3D engine. Procedural textures. Pathfinding AI. |
| 4.0 | Opus 4.5 | One conversation | Neural memory. Adaptive difficulty. Four game modes. Power-ups. Sound synthesis. |
| 5.0 | Opus 4.6 | One conversation | Evolutionary simulation. Emergent behavior. Population genetics. Procedural audio. Genome visualization. |

The pattern isn't "more features." The pattern is "deeper abstraction."

1.0 through 3.0 were about **implementation** -- can the model write working code?

4.0 was about **systems** -- can the model design interacting subsystems (memory, prediction, difficulty curves)?

5.0 is about **emergence** -- can the model design a system where the interesting behavior *isn't specified*, but arises from simple rules interacting?

That's the jump. Opus 4.6 didn't add more features to a game. It designed a system that generates its own features through evolutionary pressure. The flanking behavior, the specialization into roles, the pack hunting -- none of that is in the code. It's in the dynamics.

This is what I mean when I say the limiting factor has shifted from "can I build this?" to "can I envision this clearly enough?" I said "surprise me." The model understood that the most surprising thing isn't more complexity -- it's emergent complexity from simple rules.

## The Exponential Compression, Visualized

| Version | Year | Model | Dev Time | Complexity |
|---------|------|-------|----------|------------|
| 1.0 | 2024 | GPT-3.5 | ~4 hours | Grid + chase loop |
| 2.0 | 2024 | Claude 3.5 Sonnet | ~90 min | Web app + controls |
| 3.0 | 2025 | Claude 4 | ~5 min | 3D engine + pathfinding |
| 4.0 | 2025 | Opus 4.5 | ~1 session | Neural AI + 4 modes + audio |
| 5.0 | 2026 | Opus 4.6 | ~1 session | Evolutionary sim + emergence + procedural everything |

The development time flatlined at "one conversation" between 4.0 and 5.0. The capability didn't. The model used the same amount of time to produce something categorically more sophisticated. That's the real benchmark -- not speed, but *depth per unit time*.

## What Version 6.0 Will Tell Us

I'll run this test again when the next model ships. Same prompt: "Build FeedShyWorm 6.0. Surprise me." The delta between 5.0 and 6.0 will tell me whether the intelligence curve is still steepening or starting to plateau.

My prediction: 6.0 won't add to the game. It'll change what the game *is*. Just like 5.0 turned a game into an ecosystem, 6.0 will turn the ecosystem into something we don't have a word for yet.

That's the pattern. Each version doesn't improve on the previous one. It reframes the entire problem at a higher level of abstraction. The model isn't getting faster at the same tasks. It's getting better at seeing which tasks matter.

## The Worm as Benchmark

FeedShyWorm was never about the game. It was always about the question: what can this mind do that the last one couldn't?

1.0 proved AI could write functional code from a concept.
2.0 proved it could migrate across platforms intelligently.
3.0 proved it could handle spatial reasoning and 3D systems.
4.0 proved it could design adaptive, learning systems.
5.0 proved it could design systems that surprise their own designer.

The worm keeps getting smarter. But the real intelligence being tested was never the worm's.

---

*Built with Claude Opus 4.6 (1M context) -- March 2026*
*The game is available at [CodePen link -- coming soon]*

What will you build to benchmark the next model?
