---
created: 2026-04-18
platform: x
status: draft
title: "The harness is the room, not the furniture"
source: harness-is-the-room
cross_post: [linkedin, devto]
register: x-thread
---

# Thread: The harness is the room

**1/**
Your plugin system is either Unix or it's doomed.

Unix kernels have stayed ~20M lines for fifty years while userspace grew to include every compiler, browser, and AI framework ever written.

Your plugin-laden "extensible" framework is 10x bloatier in 18 months. Why? 🧵

**2/**
Every extensible system makes one decision that predicts its whole future:

Do plugins run **inside** the core, or **alongside** it?

Inside = privileged. Plugins can reshape core. Every "Plugin X needs a hook" becomes "let's add a hook."

Alongside = bounded. Plugins talk through a fixed interface. They can't reach in.

**3/**
Inside-style plugin architectures accumulate feature bloat until the core is the only place anyone can work. Every plugin becomes a reason to expand privileged access. A year later, 40% of the codebase is hooks.

Alongside-style stays small. Plugins are constrained by the interface, and the interface has to stay narrow enough for humans to understand.

**4/**
Unix kernels chose alongside. System calls + signals are the interface. Userspace can't reach into kernel state except through those.

Result: kernels stayed bounded. Userspace became *everything.*

**5/**
My AI agent harness (Virtual Brainstem) is ~400 lines. Ships with no features — just the orchestration loop.

Features arrive as `.py` files. Memory, weather, egg import/export, web fetch, journal — all agents. None require harness changes.

Result: 150+ agents in 6 months. Zero harness growth.

**6/**
The temptation to break the rule is constant. "Memory is fundamental — surely it should be in the core?"

I thought so for 5 minutes. Then I realized: if memory lived in the core, I couldn't have swapped localStorage for Azure Blob when porting to browser. Couldn't have added per-user partitioning. Couldn't have disabled it for privacy cases.

Memory-as-agent gave me all of those for free.

**7/**
The test: does this feature belong in the core?

1) Does it need r/w to state the bounded interface doesn't expose?
2) Is it *universal* — every plausible user wants it in the same shape?
3) Does removing it break the framework unrecoverably?

Almost everything fails #2. "Universal for current users" becomes "obstacle for next users."

**8/**
The room metaphor:

Harness = walls, doors, floor. It creates conditions for activity. It does nothing alone.

Agents = furniture. They make the room useful. You add, remove, rearrange.

Most framework designers build rooms with built-in couches. Then users want different couches. Framework becomes the couch store.

**9/**
Better: ship the harness with **nothing except the walls.** Users bring furniture. The room is reusable because it's not committed to any arrangement.

This is why I've been shipping AI tooling with aggressively sparse cores. Harness-sacred.

**10/**
If you're building one of the 50 AI frameworks launched per week right now, make this architectural decision explicitly.

Choose alongside.

Your future self will thank you when your framework isn't unmaintainable by month 18.

**11/**
Full post with the Unix analogy + practical test + memory-as-agent example:

kody-w.github.io/rappterbook/blog/harness-is-the-room

Keep the harness sacred. Keep the room empty. Let the furniture arrive as files.

/end
