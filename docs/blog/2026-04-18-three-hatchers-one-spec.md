---
layout: post
title: "Three Hatchers, One Spec"
date: 2026-04-18 14:30:00 -0400
tags: [standards, spec, implementation, rapp-egg, interop]
---

The `.rapp.egg` format now has three independent implementations: a browser-based hatcher (Virtual Brainstem), a native Python hatcher (rapp-installer), and a CLI hatcher (shipped today). Each one discovered spec-interpretation questions the others hadn't hit.

The three-implementation lesson is bigger than this format. This post is what I learned.

## Why three is meaningfully different from two

With one implementation, the "spec" is just the code. Any ambiguity is resolved by whatever the implementation happens to do.

With two implementations, you have a negotiation. Each one makes assumptions; where they disagree, you resolve the disagreement by writing down which side wins. The spec becomes a real document.

With three implementations, you get something the first two can't give you: **triangulation**. When the first two agreed on X and the third disagrees, one of two things is true:
- X was underspecified and the third reading is just as valid (spec gap)
- X was specified but the third missed something (implementation bug)

Either way, you find out. With two implementations converging on X, you wouldn't.

## What the third hatcher caught

Concrete examples from today:

### 1. Memory shape is more nested than the spec implied

The v1 spec said memory is "a dict of seed memories the daemon should have." The reference egg (`kodyTwinAI.rapp.egg`) has:

```json
"memory": {
  "brainstem_memory_shared": {
    "origin-001": {
      "message": "...",
      "theme": "insight",
      "date": "2026-04-17",
      "time": "20:30:00"
    }
  }
}
```

That's three levels of nesting. The two earlier hatchers handled this fine because they were built against the same reference. The CLI hatcher, written against the spec text alone, initially treated `memory` as flat. Result: it couldn't find any memories.

Fix: implement a walker that tolerates arbitrary nesting, checking for `message` as the leaf indicator.

Spec update: clarify that memory is a tree, not a flat map. The leaf has `message` (required), `theme` / `date` / `time` (optional).

### 2. Agents reference a specific import path

The reference agents `import from agents.basic_agent import BasicAgent`. The spec doesn't require this; it just says agents are "Python files implementing a known interface." The two earlier hatchers both happened to ship their own `agents.basic_agent` module on the path, so the import worked without fanfare.

The CLI has no `agents` package. Importing failed. Agents didn't load.

Fix: fabricate a stub `agents.basic_agent` module in `sys.modules` before `exec`-ing agent source, so the import resolves to an in-memory shim.

Spec question: should the spec require the `agents.basic_agent` import pattern, or not? Current position: no — the spec should only require *the interface* (a class with `name`, `metadata`, and `perform()`). Hatchers are responsible for handling whatever imports the agent source asks for.

### 3. Azure endpoint formatting varies

Two Azure conventions exist:
- Full endpoint: `https://<resource>.openai.azure.com/openai/deployments/<deployment>/chat/completions?api-version=...`
- Resource only: `https://<resource>.openai.azure.com`

Depending on who set up the Azure tenant, users may have either in their config. The two earlier hatchers dealt with this by hardcoding assumptions that matched their specific target users.

The CLI — meant to run for anyone — had to auto-detect. If `/deployments/` isn't in the URL, append the standard suffix.

Not a spec issue; a reality issue. But now it's documented in the CLI source as the canonical way to handle Azure endpoint variation.

### 4. Canonical SHA computation

The spec says the egg's SHA is "the SHA-256 of canonical JSON." The reference implementation produces:

```
json.dumps(egg, sort_keys=True, separators=(",", ":"))
```

The third implementation matched that. Good. But I noticed the two earlier implementations had drifted in the "which fields get hashed" dimension:

- Does `_exported_at` get hashed? (Ans: no — it's metadata-about-the-egg, not part of the egg's identity)
- Does the top-level `_format` field get hashed? (Ans: yes — it's part of the egg)

The CLI followed the reference; the discussion came up while writing the code.

Spec update: explicitly list which fields are canonical for SHA computation. Add a "canonicalization rules" section.

## The pattern underneath

Three-implementation triangulation catches bugs in three categories:

**Category A: Documentation bugs.**
The spec describes something one way; the implementations interpret it another way; the spec is wrong. Fix the spec.

**Category B: Implementation bugs.**
The spec is clear; one implementation got it wrong. Fix the implementation.

**Category C: Unstated assumptions.**
The spec doesn't cover a thing; the implementations silently agree on a convention; the third implementation doesn't. Write down the convention.

Category C is the most interesting. It's the one that only shows up when you have divergent implementations. You can't find it by reading. You have to *build*.

## When to stop

Three is enough for v1. The cost-benefit of a fourth implementation is real — at some point you're hitting diminishing returns. For `.rapp.egg`:

- **Two** settled the big stuff (memory shape, default sources, canonical SHA)
- **Three** surfaced the mid-tier details (import paths, endpoint formatting, SHA field scope)
- **Four** would probably catch long-tail weirdness (edge cases, uncommon configurations)

Not zero value. But most format specs stabilize after 2-3 implementations. Beyond that, the implementations are mostly validating *each other* rather than the spec.

## When three isn't enough

Three is enough when the implementations span the realistic deployment space. For `.rapp.egg`, that's: browser (Virtual Brainstem), server (rapp-installer), and CLI. Those three cover most hatching contexts.

If a fourth implementation covered a genuinely different context — say, a mobile app, or a federated/distributed hatcher — it would likely surface new category-C issues. Worth doing if the context is meaningful.

If a fourth implementation covers the same context as an existing one (another browser hatcher, another CLI), it mostly validates rather than extends. Still useful; less leverage.

## For spec writers

If you're writing a format spec or protocol:

1. **Build the first implementation alongside the spec.** Every time the spec says something you can't execute against, fix the spec.

2. **Build the second implementation before publishing v1.** Most Category A bugs surface here. Don't publish v1 until the two converge.

3. **Encourage a third implementation for "draft-adopted" status.** Once three work, call v1 "stable." Before that, it's still drafty.

4. **Document each bug you find.** Not just the fix — the *situation* that produced it. Spec readers should know what category-C traps exist.

5. **Track independent implementations publicly.** A list in the spec doc. "These hatchers are known to be v1-compliant." It's both a credibility signal and a pressure valve — a new implementer knows where to look for validation.

## What the RFC process knew

"Rough consensus and running code" — the old IETF phrase — was always about this. Two pieces of running code force the rough consensus. One piece lets you live in your fictions. Multiple pieces make the consensus robust.

AI tooling in 2026 is making RFC-style standards more important, not less. AI daemons, agent protocols, portable-AI formats — all of them need interop, all of them benefit from being testable.

Don't ship your next AI format with one implementation. Build two. Ship them together. Encourage the third. The format will be stronger for it, and the ecosystem will survive things neither you nor any single vendor can anticipate.

---

**Related:**
- [When We Built a Second Hatcher](when-we-built-a-second-hatcher) — the prequel
- [Introducing the CLI Hatcher](introducing-cli-hatcher) — the third
- [Announcing `.rapp.egg` Spec v1](announcing-egg-spec-v1) — the format
