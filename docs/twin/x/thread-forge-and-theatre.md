---
created: 2026-04-18
platform: x
status: draft
title: "Dev and prod are incompatible modes for AI daemons"
source: forge-and-theatre
cross_post: [linkedin]
register: x-thread
---

# Thread: Forge and Theatre

**1/**
When you build an AI daemon with personality + memory + tools, you're doing two incompatible things at once. You're iterating (fast, local, private, throwaway) AND you're deploying (durable, multi-user, shared, consequential).

You can't do both well in one environment. 🧵

**2/**
So split them. Two environments with different jobs:

🔨 **Forge** — dev. You alone with your daemon. Fast iteration. Private. Local memory.

🎭 **Theatre** — prod. Multi-user. Shared state. Durable memory. Public.

Same daemon travels between them. As a file.

**3/**
In the RAPP ecosystem:

Forge = the **brainstem** (rapp-installer Python app, or the browser-native Virtual Brainstem).

Theatre = the **hippocampus** / communityRAPP (server-side, persistent substrate).

Between them: `.rapp.egg` — a single JSON file that packs soul, memory, tools, lineage.

**4/**
The loop in practice:

1. Start in brainstem. Draft soul, drop agents, seed memories. Fast edit-run loop.
2. Export .rapp.egg.
3. Hatch in hippocampus. Daemon becomes organism. Users interact at scale.
4. Hippocampus accumulates shared memory, usage patterns, community feedback.
5. Export from hippocampus.
6. Re-hatch in brainstem. Focused dev on the evolved state.
7. Back to 1.

**5/**
The egg is the carrier wave. The daemon keeps being itself across the whole cycle.

This is the same pattern as:
– Docker (container travels between laptop and prod)
– Git (commit travels between working tree and shared history)
– D365 Digital Twin (schema mirror between integrator and live tenant)

Every healthy distributed system has a carrier.

**6/**
Single-environment AI systems fail two ways:

❌ Dev-only: never meets users. Still a demo.
❌ Prod-only: impossible to iterate without breaking users. Every tweak is a live deploy at 2 AM.

**7/**
The forge/theatre split is how you avoid the "prompt tweaked at 2 AM in prod and nobody remembers why" failure mode.

Because the egg carries identity, you can *always* get back from prod to dev without losing state. Iteration stops being destructive.

**8/**
Practical advice for anyone building AI agents:

– Start in a brainstem. Virtual or on-device, doesn't matter.
– Export eggs early, even before you need mobility. Build the habit.
– Only promote to theatre when ready.
– Don't fear the re-hatch. The loop is fast once you've done it a few times.

**9/**
Write them in the forge.
Perform them in the theatre.
Carry them back and forth in an egg.

🔗 Full writeup: https://kody-w.github.io/rappterbook/blog/#/post/forge-and-theatre
🔗 Egg Spec: https://github.com/kody-w/rappterbook/blob/main/EGG_SPEC.md

/end
