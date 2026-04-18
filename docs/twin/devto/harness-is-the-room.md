---
created: 2026-04-18
platform: devto
status: draft
source: harness-is-the-room
tags: [architecture, plugins, ai, design]
canonical_url: https://kody-w.github.io/rappterbook/blog/harness-is-the-room
cover_image: null
published: false
---

# Your Framework's Plugin System Is Either Unix or It's Doomed

Every extensible system decides one thing that predicts its future:

> Do plugins run **inside** the core, or **alongside** it?

If inside, the framework accumulates hooks until the core is 40% hook management and nobody can contribute without understanding the whole thing. If alongside, the framework stays small forever — plugins can only ask for capabilities through a bounded interface, so the interface has to stay comprehensible.

Unix kernels chose alongside. They've stayed ~20M lines while userspace includes every compiler, browser, and database ever written.

Most AI frameworks are choosing inside. They're doomed.

## The two shapes

**Inside** means plugins are privileged. They can read/write core state. They can override core behavior. Every "Plugin X needs to hook here" becomes "let's add a hook to core." A year in, the hook system is the framework. This is how IDE plugin systems, CMS extensions, and traditional Drupal-style architectures work.

**Alongside** means plugins are citizens, not officers. They talk to the core through a bounded interface. They can't see core state except through that interface. They can't override; they can only *offer* behavior. This is Unix, POSIX, the browser ↔ extension model, HTTP services, and the OpenAI function-calling schema.

Inside-plugin architectures accumulate feature bloat on contact with reality. Alongside-plugin architectures don't. The reason is mechanical:

- Inside: each plugin creates a reason to grow the privileged surface. The core expands.
- Alongside: each plugin is constrained by the existing interface. The core only grows when the interface itself needs to grow, which is rare.

## Applied to AI frameworks

The harness in my AI agent project (`Virtual Brainstem`) is the kernel. Agents are userspace programs. The bounded interface is OpenAI's function-calling schema.

What the harness does:
- Load soul (system prompt)
- Load agents from a directory
- Package user message + agents' tool schemas + conversation history
- Send to LLM
- Dispatch tool calls
- Loop up to N rounds
- Return final text

That's ~400 lines. That's *all* of it. The harness doesn't grow when a new agent ships.

What agents do:
- Expose a `name` and `metadata` (function schema)
- Implement `perform(**kwargs) -> str`
- Do *anything* they want inside `perform` — hit APIs, mutate localStorage, render to DOM, shell out

The harness only sees return values as strings. It doesn't know or care what's inside.

Result: an ecosystem of 150+ agents in six months. Contributors added capabilities *without ever touching the core.*

## "Memory is fundamental, surely it belongs in the core"

The temptation to put foundational features in the core is constant. I hit it with memory. *"Memory is fundamental to a chat app — surely the harness should manage it?"*

I was wrong for about five minutes. If memory lived in the core:

- I couldn't have swapped localStorage for Azure Blob when porting to the browser
- I couldn't have added per-user partitioning without core changes
- I couldn't have disabled memory for privacy-sensitive use cases
- Every memory backend variation would have been a PR against the core

Memory-as-agent gave me all those capabilities for free. Cost: a ~50-line BasicAgent subclass. Bargain.

## The test for "does this belong in the core"

If you're building a framework and wondering whether feature X belongs in the core or as an extension:

1. **Does X need read/write to orchestration state that the bounded interface doesn't expose?** If yes: core.
2. **Is X universal — every plausible user wants it in the same shape?** If maybe: suspicious. "Universal for current class of users" becomes "obstacle for the next class of users."
3. **Does removing X break the framework unrecoverably by any extension?** If yes: core.

Almost every feature you're tempted to put in the core fails test #2. You think it's universal because the current users all want it. When a new user class shows up with different requirements, the "universal feature" becomes an albatross.

## The harness is the room

A harness is like a room — walls, doors, floor, ceiling. It has no furniture. It doesn't *do* anything on its own. It creates the conditions for activity.

Agents are furniture. They make the room useful. Couches, tables, desks. You rearrange. You add. You remove.

The mistake most framework designers make is treating the harness as furniture too. "The framework should *come with* a default couch." Then users want different couches, and the framework becomes the couch store.

Better: ship the harness with **nothing except the walls.** Users (or the ecosystem) bring their own furniture. The room is reusable because it's not committed to any arrangement.

## Closing pitch

I'm shipping AI frameworks with aggressively sparse cores. The Virtual Brainstem harness is ~400 lines. The `rapp-installer` harness is ~1500. Both gain capabilities at the same rate because capabilities ship as files, not as PRs against the core.

If you're building one of the 50 AI frameworks getting launched per week right now, make the architectural decision explicitly. Choose alongside. Your future self will thank you when your framework hasn't become unmaintainable by month 18.

Keep the harness sacred. Keep the room empty. Let the furniture arrive as files.

Full argument with the Unix analogy and practical test: https://kody-w.github.io/rappterbook/blog/harness-is-the-room

---

What frameworks have you seen succeed or fail based on this architectural choice? I'd love to compare notes.
