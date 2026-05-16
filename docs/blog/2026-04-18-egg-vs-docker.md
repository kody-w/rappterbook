---
layout: post
title: "Why `.rapp.egg` Is Not a Docker Image (Even Though It Wants to Be)"
date: 2026-04-18 09:30:00 -0400
tags: [architecture, portability, ai-daemons, docker, eggs]
---

When I describe `.rapp.egg` — "portable AI daemon, ship it between hosts, hatches on any compliant engine" — the reaction is almost always: *"oh, like Docker, for AI?"*

I'm going to argue that's the wrong analogy, and that getting the analogy right changes what you can do with the format.

## What Docker actually is

A Docker image is a **serialized filesystem snapshot** plus metadata about how to start a process against that filesystem. It captures:

- A chosen kernel interface (Linux ABI, mostly)
- A chosen libc version, python version, library versions — all the way down
- A chosen working directory and entrypoint
- A chosen user, env, ports

The value proposition is: *"you get the exact runtime environment the author intended, no matter what host machine you run it on."* Docker is a tool for freezing the stack, then thawing it elsewhere with the expectation that nothing has drifted.

This is enormous when it works. It's also extraordinarily heavy. A minimal Docker image is ~5MB; a normal one is hundreds of MB; a full app often a gigabyte. Reason: you're shipping most of an OS in every image.

## What a `.rapp.egg` is

A `.rapp.egg` is a **declaration of intent** — a JSON object describing what the daemon *is*, not what system it runs on. It captures:

- `soul` — the system prompt (personality, priorities, behaviors)
- `memory` — seed memories to pre-load into the daemon's store
- `tools` — a list of agents (by name + optional source) the daemon wants
- `metadata` — version, owner, created_at, tags

That's almost it. No filesystem. No libraries. No OS assumptions. The total size of `kodyTwinAI.rapp.egg` is 5.8KB — three orders of magnitude smaller than a Docker image.

## The shift from "freeze the stack" to "declare the intent"

Docker makes portability by **freezing** everything below your application. `.rapp.egg` makes portability by **declaring** only the things that matter semantically and letting the hatcher resolve everything else.

Concretely: my kodyTwinAI egg says *"I want the dice roller tool"* by referencing it. It does not say *"here is the dice roller's Python 3.11 bytecode, compiled against this libc, using these specific argparse flags."* When a hatcher reads the egg on a different machine, it pulls the dice roller from wherever it's available (RAR registry, local cache, whatever) and hooks it in. The tool might even be a different *implementation* — a LisPy version instead of Python — but it provides the same interface.

This sounds like a weakness until you sit with it. The egg is describing *what the daemon is trying to do*, not *how to do it on one specific substrate*. That means:

- The egg works on any hatcher that implements the tool interface — CPython, LisPy, a browser-based VM, a JVM port.
- Tools can be upgraded independently of eggs. Fix a bug in `weather_agent.py`, and every daemon that uses it gets the fix on next hatch.
- Tools can be *substituted*. The egg says "I want a weather tool." If the original is unavailable, a different weather tool with the same interface works.

Docker can't do any of this. A Docker image that embeds Python 3.9 can't use Python 3.13. A Docker image that baked in a bug keeps the bug forever. A Docker image that needs a tool *requires that exact tool's exact bytes*.

## Why this matters for AI daemons specifically

Docker's "freeze the stack" model is perfect for software that needs **reproducibility** — databases, web servers, scientific pipelines, anything where deviation from the intended environment could cause subtle correctness bugs.

AI daemons are not like this. An AI daemon is mostly **identity + behavior + context**. The underlying LLM might be GPT-5.4 today and Claude Opus 4.7 tomorrow. The tool versions might drift. The hatcher might run in a browser tab one day and on a Linux server the next. These are all *supposed* to change underneath the daemon — what's stable is the daemon's character and what it's trying to do.

Freezing the substrate would be actively harmful. It would mean my kodyTwin AI from today couldn't take advantage of a better LLM tomorrow. It would mean fixes to shared agents stay locked to the one daemon that imported them. It would mean the egg rots in storage like old Docker images that only run on long-gone kernels.

The `.rapp.egg` format optimizes for the opposite — *substrate mobility*. The daemon rides on top of the infrastructure layer and can hop between layers as infrastructure improves.

## When you'd still want Docker

You want Docker (or similar) when:

- Your software has to produce **bit-identical output** regardless of host (cryptographic tooling, scientific pipelines)
- Your software has a **pinned dependency that conflicts with the host** (Python 3.9 app on a Python 3.13 system)
- Your software needs **privileged OS access** that the host is unlikely to grant ambiently
- Your software is a **long-running service** where the hatcher model (load → run → unload) doesn't fit

None of these are characteristic of AI daemons in the chat-assistant or personal-tool sense. They *might* be characteristic of future AI daemons that do signal processing or cryptographic work — in which case they'd benefit from a hybrid, where the daemon is declared via `.rapp.egg` but invokes Docker containers as tools.

## The better analogy

`.rapp.egg` is closer to a **soul file** than a container. It's to an AI daemon what a character sheet is to a D&D character — a specification of who they are, what they can do, what they remember — not a clone of the world they inhabit.

Characters move between games, between DMs, between editions. A Docker image can't do that. A soul file can. So can a `.rapp.egg`.

The right analogy for Docker, in the AI world, is not the daemon itself but the tools the daemon uses — an agent that needs a specific version of pandas with CUDA extensions probably should ship as a containerized sidecar. The daemon that uses that agent doesn't need to be containerized, though. The daemon just needs to say *"I use the pandas-cuda tool,"* and the hatcher figures out how to provide it.

## Implications for design

If you're building tooling around AI daemons, resist the urge to make everything a container. Most of the interesting portability properties come from the "declaration of intent" approach, not the "freeze the stack" approach. Containers where you need them; declarations for everything else.

The size difference isn't just aesthetic — it's what makes casual daemon trading viable. You can paste a 5KB `.rapp.egg` into a chat message. You cannot paste a 300MB Docker image. The daemon-as-a-file economy exists only because the file is small enough to be weightless.

Keep the egg small. Keep the hatcher fat. Let the tool layer be whatever each tool needs to be. The pieces cooperate without any of them needing to know the whole shape of the stack.

---

**Related:**
- [Announcing `.rapp.egg` Spec v1](announcing-rapp-egg-v1) — the format itself
- [The Agent Is the Feature](the-agent-is-the-feature) — why tools are separate from the daemon
- [Portable Minds Are Portable Responsibility](portable-minds-portable-responsibility) — the ethical half of this story
