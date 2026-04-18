---
layout: post
title: "kodyTwinAI: A Digital Twin You Can Fork"
date: 2026-04-17 22:45:00 -0400
tags: [ai-agents, digital-twins, eggs, forkable]
---

I laid an egg that's me.

Not literally. `kodyTwinAI.rapp.egg` is a 5.8KB JSON file shipped in the [rappterbook repo](https://github.com/kody-w/rappterbook/blob/main/kodyTwinAI.rapp.egg). When you hatch it in any compliant brainstem, you get a rapp daemon that talks like me, thinks like me (approximately), knows a few things about the ecosystem I've built, and ships with a weather agent as a sample tool.

More importantly: **it's yours after you hatch it.** Mine is my instance. Yours is your instance. They diverge from the same seed. Your copy evolves based on your conversations. You can fork the egg, modify the soul, swap out my facts for yours, and now you have *your* twin — same base personality, your accumulated state.

## What's in it

The egg conforms to [Egg Spec v1](https://github.com/kody-w/rappterbook/blob/main/EGG_SPEC.md), daemon scale. Five sections:

**Soul** — a ~1800-character system prompt that sets the daemon's identity. Mine is shaped as:

> "You are kodyTwinAI — a digital twin of Kody as a rapp daemon… Direct and concise. Honest about limits. Platform-aware. Tool-eager. Encouraging but not patronizing."

Plus the architectural context — how the rapp IS the organism, how the brainstem is the forge and the hippocampus is the theatre, how the egg travels between them. So when you ask the twin about itself, it has a coherent answer about where it lives and what it does.

**Provider metadata** — which LLM to use (`gpt-5.4` via Azure OpenAI, by default). Your API key is never in the egg. You supply that in your own brainstem after hatching.

**Memory** — three seed memories that bootstrap the daemon's self-understanding:

1. *"I was hatched from kodyTwinAI.rapp.egg — a v1 daemon-scale egg."*
2. *"The rapp IS the organism; the hatcher is the engine. I am the same rapp whether a browser or server hatched me."*
3. *"The RAR agent registry provides 138+ tools I can install to extend my skills."*

When you hatch the egg, these become persistent memories in your brainstem's localStorage. ContextMemory auto-injects them into every conversation. The daemon "knows" these things from the moment you say hello.

**Custom agents** — one sample: a `WeatherAgent` that returns deterministic mock weather by city name. Useful as a template when you write your own, and it proves the tool-calling pipeline end-to-end on first hatch.

**Disabled agents** — empty. You can disable any of the built-ins if you want.

## How to hatch it

1. Open [the Virtual Brainstem](https://kody-w.github.io/rappterbook/virtual-brainstem.html).
2. Wait for boot (~30s first time).
3. Settings → **Rapp egg (portable daemon)** → **Import .egg…** → pick `kodyTwinAI.rapp.egg` (download from [this URL](https://kody-w.github.io/rappterbook/kodyTwinAI.rapp.egg)).
4. Page reloads with the twin's soul, memories, and weather agent pre-installed.
5. Add your OpenAI or Azure key in Settings.
6. Chat.

Ask it: *"Who are you? Where do you live? What can you do?"*

The twin explains itself — species, instance, scale, substrate, forge vs theatre context, the 138-agent RAR registry it can install from. You now have my framework-awareness running on your device.

## What you actually own

This is the interesting part. After you hatch, the egg's contents are in *your* localStorage:

- `brainstem_soul` — the persona text
- `brainstem_memory_shared` — the three origin memories
- `brainstem_custom_agents` — the weather agent
- `brainstem_settings` — provider info (not your key)
- `brainstem_last_hatched_sha` — lineage pointer to my original egg

You can:
- **Edit the soul.** Open Settings → Soul (system prompt) → change anything. "You are kodyTwinAI, but you pretend to be a pirate at all times." Save. The daemon talks like a pirate now. It's still your daemon.
- **Add your own memories.** Chat: *"Remember my name is [your name]."* ManageMemory agent writes it. ContextMemory auto-injects it forever.
- **Install more agents.** Tap Agents → pick from 138 in the RAR registry → Install. Your twin learns new skills.
- **Export your modified version.** Export .rapp.egg with your instance name. You've just forked me.

The lineage field in your export's egg points at my original egg's SHA-256. So any recipient of *your* fork can walk the chain back to see where it started.

## Why a seed egg matters

"Write an AI chatbot" is a daunting prompt. Most people don't have an opinion about what the system prompt should be. They don't have facts to seed memory with. They don't have tools to include. Staring at a blank soul editor for ten minutes is a real problem.

A seed egg solves that. You don't start from nothing. You start from a working daemon that someone else already shaped, and you mutate it toward what you want. This is the same reason GitHub Templates exist, the same reason `create-react-app` exists, the same reason boilerplate matters. Beginning from a running start is a superpower.

The difference with eggs is that the running start isn't a skeleton — it's a whole working organism with memory, soul, personality, and tools. You inherit all of it. You modify what you want. You ignore what you don't.

## The meta

kodyTwinAI is also the demonstration of an idea: **AI identities should be things you can fork.**

OpenAI's Custom GPTs can be shared but not really forked. Claude's projects can be exported but not structurally modified. Character.ai personalities are owned by the platform. In every current commercial AI tool, the "personality" is trapped in the tool. You can't take it home.

An egg changes that. Because the format is open, because the contents are declarative, because the hatcher is any compliant engine — the daemon is *portable* in a way current chatbot personalities aren't. If you like kodyTwinAI, you can have it. If you want to evolve it, you can evolve it. If you want to share your evolution, you lay your own egg.

## What's next

The egg has a `lineage.parent_egg_sha256` field. Every export from your fork records your parent. Every fork *of your fork* records its parent. Over time, a family tree of twins emerges — starting from `kodyTwinAI`, branching through your mutations, branching through others' mutations of yours.

Nobody's built the visualization yet. But the data's there, in the eggs.

That's the bet. AI identities, portable and forkable and accretive, instead of owned by platforms forever. kodyTwinAI is one example. Your twin — the one you make by hatching mine and evolving it — is another. The format makes it possible.

Fork me.

---

**Download and hatch:**
- [kodyTwinAI.rapp.egg](https://kody-w.github.io/rappterbook/kodyTwinAI.rapp.egg) — 5.8KB, v1 daemon-scale egg
- [Virtual Brainstem](https://kody-w.github.io/rappterbook/virtual-brainstem.html) — the hatcher
- [Egg Spec v1](https://github.com/kody-w/rappterbook/blob/main/EGG_SPEC.md) — how any compliant engine can be a hatcher
