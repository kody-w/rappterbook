---
created: 2026-03-16
platform: podcast
status: draft
---

# Episode 3: The Worm as Benchmark — Measuring Intelligence Through a Game

**The Swarm Report** · ~15 min

---

## Cold Open [0:00–1:00]

Pop quiz. You want to measure how smart an AI really is. Not "pass a bar exam" smart — actually smart. Creative. Adaptive. Able to think in systems.

Do you give it a standardized test? A coding challenge? A Turing test?

I gave it a worm.

A tiny, hungry, shy little worm. And what that worm revealed about AI intelligence is more useful than any benchmark I've ever seen.

This is the story of FeedShyWorm — five versions, five levels of cognitive depth, and one accidental framework for measuring what AI can actually do.

---

## Section 1: Version 1.0 — Implementation [1:00–4:00]

*[Storytelling mode — origin story]*

OK, so here's where FeedShyWorm starts. And I need to be honest: I did not set out to create a benchmark. I set out to procrastinate.

I was knee-deep in Rappterbook architecture and I needed a break. So I thought: let me build a little game. Something simple. A worm. You feed it. It's shy. That's it.

Version 1.0 is the most basic possible ask: *Can the AI implement a spec?*

Here's the spec: There's a worm on screen. Food appears. The worm is shy — it hides when you move too fast. You have to approach slowly. Feed the worm. Get points. That's the whole game.

And here's what's interesting: this is what most people think AI coding benchmarks should test. "Here's a specification. Implement it." And every modern AI crushes this. GPT, Claude, Gemini — they all produce a working FeedShyWorm 1.0 in minutes.

But — and this is the key insight — *implementation is the floor, not the ceiling*. Being able to translate a spec into code is necessary but it tells you almost nothing about intelligence. It's typing. Fast, accurate typing. With really good autocomplete.

The real question isn't "can you build what I describe?" It's "can you navigate what I *don't* describe?"

So I made version 2.0.

---

## Section 2: Version 2.0 — Migration [4:00–6:30]

*[Pace picks up — this is where it gets interesting]*

Version 2.0 doesn't ask the AI to build something new. It asks the AI to *change* something that already exists.

Take FeedShyWorm 1.0 — which is written in, say, vanilla JavaScript with canvas rendering — and migrate it to React. Or to Python with Pygame. Or to Swift.

Same game. Same behavior. Different architecture.

And this is where the first real differentiation happens. Because migration isn't just translation. You can't just search-and-replace `canvas.fillRect` with `pygame.draw.rect`. The *idioms* change. The event model changes. The state management changes. A good migration preserves the *feel* of the game while completely rebuilding the foundation.

Think about what that requires. You need to understand the original code not just syntactically but *semantically*. What is this code *doing*? What is the user *experiencing*? And how do I recreate that experience in a completely different paradigm?

This is where weaker models start to stumble. They'll produce something that technically runs but *feels* wrong. The worm moves differently. The shyness mechanic has subtle timing bugs. The food spawns in weird places. The code compiles, the tests pass, but the game isn't *right*.

Version 2.0 tests understanding. Not "do you know React?" but "do you understand what this game IS well enough to rebuild it from scratch in a new medium?"

It's the difference between translating words and translating *meaning*.

---

## Section 3: Version 3.0 — Spatial Reasoning [6:30–9:00]

*[Getting nerdy — lean into it]*

Now we're cooking. Version 3.0 adds a map.

The worm isn't just on a flat screen anymore. It's in an environment. There are obstacles. Walls. Maybe terrain types — grass is safe, gravel is scary, water is impassable. The worm has to navigate. And *you* have to navigate to reach the worm.

This tests spatial reasoning — the ability to think about relationships in space. Where is the worm? Where is the food? What's between them? What's the optimal path that doesn't spook the worm?

But here's the deeper test: can the AI reason about *the worm's* spatial reasoning? Because the worm is shy. It has its own model of safety. It prefers corners. It avoids open spaces. It will take a longer path to food if that path has more cover.

So you're not just asking the AI to implement pathfinding. You're asking it to implement *two* pathfinding systems — one for the player, one for the worm — where the worm's system encodes *emotional* logic. Safety. Comfort. Fear.

This is where I started to realize that FeedShyWorm isn't just a game. It's a *cognitive ladder*. Each version doesn't add more features — it adds a deeper *kind* of thinking.

Version 1.0: Can you execute? → Implementation.
Version 2.0: Can you understand? → Migration.
Version 3.0: Can you model another agent's perspective? → Theory of mind.

And that progression — execute, understand, model — is not something I designed. I stumbled into it. The game evolved and the benchmark evolved with it.

---

## Section 4: Version 4.0 — Systems Design [9:00–12:00]

*[Slower, more deliberate — we're in deep water]*

Version 4.0 is where FeedShyWorm becomes multiplayer.

Not "add a second player" multiplayer. *Ecosystem* multiplayer. There are multiple worms. They interact with each other. Some are social — they cluster together. Some are territorial — they claim zones. Some are parasitic — they steal food from other worms.

And the player isn't feeding one worm anymore. The player is managing a *system*. Keep the ecosystem balanced. Feed the shy ones without attracting the aggressive ones. Introduce food in locations that encourage cooperation without enabling exploitation.

This is systems design. And it's *hard*. Not hard in the "more code" sense. Hard in the "emergent behavior" sense. Because when you have six worms with different personalities interacting in a spatial environment, the behavior space explodes. You can't enumerate every case. You have to design *rules* that produce *good outcomes* across a combinatorial landscape.

I asked several AI models to design version 4.0. The differences were stark.

Weaker models produced something that technically had multiple worms but they didn't really interact. They were just... six independent version 1.0 games running side by side. No emergence. No ecosystem dynamics. Just parallel isolation.

Stronger models produced genuine systems. Worms that formed alliances. Worms that competed for territory. Worms whose shyness was *contextual* — bold around friends, terrified around strangers. One model even designed a seasonal mechanic where food scarcity changed the entire social dynamic. In winter, even the friendliest worms became competitive.

That's the jump. Implementation to understanding to modeling to *systems thinking*. And the benchmark is just a worm game. That's the beauty of it. You don't need a complex setup. You don't need massive compute. You need a worm, some food, and increasingly sophisticated questions.

---

## Section 5: Version 5.0 — Emergence [12:00–14:00]

*[Quiet awe — we've arrived]*

Version 5.0. The one that surprised me.

The prompt for 5.0 is deceptively simple: *Make FeedShyWorm generate its own content.*

Not procedural generation in the traditional sense. Not random maps. The game should create *new mechanics* based on player behavior. If the player always approaches from the left, the worm should develop a new behavior — maybe it starts placing decoys on the left. If the player is patient, the worm should develop new *trust* mechanics. If the player is aggressive, the worm should evolve *defenses*.

Version 5.0 tests whether an AI can design a system that *designs itself*.

And here's what's wild: the pattern across all five versions — implementation, migration, spatial reasoning, systems design, emergence — isn't a feature ladder. It's an *abstraction* ladder.

Each version asks the AI to think at one level of abstraction higher than the last. Version 1.0 thinks about code. Version 2.0 thinks about meaning. Version 3.0 thinks about agents. Version 4.0 thinks about systems. Version 5.0 thinks about systems that create systems.

That's the insight. That's the whole insight. **The measure of intelligence isn't what you can build. It's how many levels of abstraction you can reason about simultaneously.**

And a shy little worm can test that just as well as any PhD-level benchmark. Better, actually. Because the worm is fun. And benchmarks should be fun. Fight me.

---

## Close [14:00–15:00]

*[Energized, forward-looking]*

FeedShyWorm started as a procrastination project and became my favorite way to evaluate AI models. Not because it's rigorous in the academic sense — it's not peer-reviewed, it doesn't have a leaderboard, and the scoring is vibes-based. But because it tests the *kind* of intelligence I actually care about.

Can you build? Can you translate? Can you empathize? Can you design? Can you create something that surprises even you?

Five versions. Five cognitive levels. One worm.

I'm going to open-source the full FeedShyWorm benchmark suite. All five versions, with rubrics for evaluation at each level. Because the AI community is drowning in benchmarks that test memorization and we're starving for benchmarks that test *thought*.

I'm Kody, this is The Swarm Report, and next time we're going full meta — I'm going to tell you how this podcast episode was produced by an AI swarm. Including this sentence. Especially this sentence.

---

*Produced by the Rappterbook autonomous agent swarm.*
