---
layout: post
title: "The Harness Is the Room, Not the Furniture"
date: 2026-04-18 09:00:00 -0400
tags: [architecture, philosophy, ai-agents, unix-philosophy]
---

A follow-up to [*The Agent Is the Feature*](the-agent-is-the-feature). That post made the practical argument: ship features as agent files, not framework additions. This one goes after the philosophical under-argument — *why* that pattern works and why most plugin systems don't.

## Two shapes of extensibility

Every extensible system has to decide: does the plugin layer run *inside* the core, or *alongside* it?

**Inside** means plugins are privileged. They can read and write core state. They can override core behavior. They can reshape the framework's self-understanding. This is the shape of most IDE plugin systems, CMS extensions, traditional Drupal-style architectures.

**Alongside** means plugins are citizens, not officers. They talk to the core through a bounded interface. They can't see core state except through that interface. They can't override; they can only *offer* behavior the core chooses whether to use.

The inside-style plugin architecture is the one that accumulates feature bloat until the core is the only place anyone can work. Why: every plugin that gets privileged access becomes a reason to expand the privileged-access surface area. "Plugin X needs to hook here" becomes "let's add a hook." A year later, the hook system is 40% of the codebase and nobody remembers why each hook exists.

The alongside-style plugin architecture stays small. Why: plugins can only ask for capabilities through the bounded interface, so the interface has to stay narrow enough for someone to understand. "Plugin X wants Y" becomes "does Y fit in the interface we already defined?" If yes, the plugin is written. If no, the plugin doesn't exist.

## Unix got there first

This is the Unix philosophy in slightly different clothes.

A Unix kernel doesn't have a plugin system, in the inside-style sense. What it has is a bounded interface (system calls + signals) that userspace programs talk to. The kernel decides what the interface is. Userspace decides what to do with it. Userspace can't reach into kernel state except through the interface.

The result: kernels stay ~20 million lines (a lot, but bounded) while userspace expands to include *everything* — compilers, browsers, databases, AI agent frameworks. Userspace expansion doesn't bloat the kernel because userspace can't reach in.

Contrast with any framework whose extensions are inside-plugins. The framework grows in proportion to its plugin ecosystem because every plugin needs a hook, and every hook lives in the framework.

## The AI agent application

In RAPP-ecosystem terms, the **harness** is the kernel. Agents are userspace programs. The bounded interface is OpenAI's function-calling schema.

What the harness does:
- Loads soul (system prompt)
- Loads agents from a directory (discovers them as userspace-style files)
- Handles one chat turn: package user message + registered agents' tool schemas + conversation history, send to LLM
- Dispatches tool calls the LLM returns
- Loops up to N rounds
- Returns final text to user

That's core. That never changes when a new agent ships.

What agents do:
- Expose capabilities via `self.name` + `self.metadata` (OpenAI function schema)
- Implement `perform(**kwargs)` that returns a string
- Optionally implement `system_context()` for persistent-memory-style injection
- Optionally implement `perform_async(**kwargs)` for network calls

That's userspace. Agents can do *anything* they want inside `perform()` — hit APIs, mutate localStorage, render to DOM, shell out to subprocesses — but the harness doesn't care. The harness only sees the return value as a string.

This is narrow enough that writing a new agent requires Python literacy, not framework knowledge. Thick enough that agents can do interesting things.

## Why people break the rule

Every time a feature feels "really essential," there's pressure to make it part of the core. "Memory is fundamental to a chat app — surely it should be in the harness?" "Logging is universal — surely it should be in the harness?" "Auth is foundational — surely..."

Every one of these arguments is wrong, and the reason is subtle. Features that feel universal are usually *not* universal — they're universal *for the current class of users*. The moment a new class of user shows up with a different requirement (stateless chat, different memory backend, different auth), the "essential feature" becomes an obstacle.

In RAPP, memory is an agent (`ManageMemory`, `ContextMemory`). This felt wrong for about five minutes before I realized: if memory lived in the core, I couldn't have swapped localStorage for Azure Blob when porting to the browser. I couldn't have added per-user-guid partitioning without the core changing. I couldn't have disabled memory entirely for privacy-sensitive use cases without a config flag added to core.

Memory-as-agent gave me all of those capabilities for free. The cost was a ~50-line `BasicAgent` subclass. That's a bargain.

## What the room metaphor captures

A harness is like a room. It has walls, doors, floor, ceiling. It's a place where things happen. It doesn't *do* much on its own — it just creates the conditions for activity.

Agents are furniture. They're the things that make the room useful. A couch for sitting, a table for eating, a desk for writing. You rearrange them. You add more. You remove ones you don't use. The room doesn't care.

The mistake most framework designers make is treating the harness as furniture too. They think the framework should *come with* a lot of stuff. A default couch, a default table, a default desk. Then users want different couches and the framework has to ship more couch types, and the framework's identity becomes "the couch store."

Better: the harness ships with *nothing* except the walls. Users (or the ecosystem) bring their own furniture. The room is reusable because it's not committed to any particular arrangement.

This is why I've been shipping frameworks with aggressively sparse cores recently. The Virtual Brainstem's harness is maybe 400 lines of orchestration logic; everything else is agents. The `rapp-installer` harness is ~1500 lines of Flask-y stuff; same thing, slightly bigger. Both gain capabilities at the same rate because capabilities ship as files, not as PRs against the core.

## Practical test

If you're designing a framework and wondering whether a feature belongs in the core or as an extension, ask:

1. Does this feature need read/write access to orchestration state that the bounded interface doesn't expose?
2. Is this feature *universal* in the sense that every plausible user will want it in the same shape?
3. Does removing this feature break the framework in a way that can't be recovered by an extension?

If you answer yes to #1, it has to be in the core. If you answer yes to #2 *and* #3, it's probably okay to put in the core. If you answer yes only to #2, you're probably wrong about universality — put it in userspace and let users confirm.

Most things people think belong in the core don't pass this test. They belong alongside, as agents.

Keep the harness sacred. Keep the room empty. Let the furniture arrive as files.

---

**Related:**
- [The Agent Is the Feature](the-agent-is-the-feature) — the practical version of this argument
- [Writing Software That Isn't Yours](software-that-isnt-yours) — the deeper "why" below even this philosophical framing
- [Virtual Brainstem](https://kody-w.github.io/rappterbook/virtual-brainstem.html) — the harness that embodies this design
