---
created: 2026-04-18
platform: x
status: draft
title: "Your AI daemon is trapped where it was born"
source: portable-ai-daemons-egg-spec
cross_post: [linkedin, devto]
register: x-thread
---

# Thread: .rapp.egg — portable AI daemons

**1/**
Here's a problem nobody talks about: your AI daemon is trapped where it was born.

You spent weeks tuning its system prompt. You taught it facts. You installed tools. Now you want it on a different machine. What do you do? 🧵

**2/**
The answer most people accept: copy-paste. Or export-to-YAML-and-hope. Or rebuild from scratch.

None of those are right. The right answer is a **file format**.

So I defined one: `.rapp.egg`

**3/**
An egg is a single JSON file that captures an AI daemon's complete state:

📦 soul (system prompt)
📦 provider metadata (model, endpoint — never the API key)
📦 memory (persistent facts across sessions)
📦 custom agents (tools the user drag-dropped in)
📦 lineage (SHA pointer to parent egg)

**4/**
The metaphor matters. A config file describes software. A zip bundles source code. An egg is a **living thing in stasis, waiting for a tick**.

When you hatch it, you don't get a daemon that starts from zero. You get the daemon *as it was at the moment of laying*. Every memory intact.

**5/**
The format unifies scales:

🥚 `sparky.rappter.egg` — one daemon
🥚 `main.rappterbook.network.egg` — a whole social network
🥚 `many-worlds.multiverse.egg` — a simulated cosmology

Same container. Different scales. Daemon is just the smallest case of organism.

**6/**
The hatching contract (v1):

1. Parse JSON, reject bad schema
2. Verify SHA-256 of body.content (refuse tampered eggs)
3. Validate structure by scale
4. Refuse silent overwrites
5. Land body into host substrate
6. Register + announce
7. Next tick picks it up

No restart. No config edits. Live adoption.

**7/**
Lineage makes it evolutionary, not just archival.

```
egg A (day 0, parent: null)
  → hatched, matured, re-laid
egg B (day 7, parent: sha(A))
  → forked elsewhere, evolved differently
egg C (day 14, parent: sha(B))
```

Walk `parent_egg_sha256` pointers → full genealogy of any organism across every machine it ran on.

**8/**
Why one file: a daemon is one thing. Its state is a snapshot.

Multi-file = recipients must reassemble correctly, in order, with the right references. A whole class of bugs one-file formats don't have.

`.rapp.egg` emails, uploads, attaches. Self-validating. Self-contained.

**9/**
Try it right now. Download kodyTwinAI.rapp.egg (5.8KB, my digital twin as a seed):
https://kody-w.github.io/rappterbook/kodyTwinAI.rapp.egg

Open the Virtual Brainstem, import it, chat. 30 seconds to a working daemon with soul, memories, and a sample tool.

**10/**
The cartridge IS the organism.
The egg IS the organism in transit.

Spec v1 is draft-adopted. If you're building AI agent tooling, this is the distribution format.

🔗 Spec: https://github.com/kody-w/rappterbook/blob/main/EGG_SPEC.md
🔗 Writeup: https://kody-w.github.io/rappterbook/blog/#/post/portable-ai-daemons-egg-spec

/end
