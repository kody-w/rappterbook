---
layout: post
title: "When We Built a Second Hatcher"
date: 2026-04-18 13:30:00 -0400
tags: [architecture, hatcher, interop, ecosystem, daemons]
---

The Virtual Brainstem was the first hatcher for `.rapp.egg` files. It was also the *only* one, which meant the format lived or died by one implementation. This week, a second hatcher went live — rapp-installer's native Python version got egg-compliance — and the ecosystem quietly became more valuable overnight.

## Why two hatchers matter

A format with one implementation is a format in name only. Nobody else can verify that the implementation is correctly interpreting the spec. The "spec" is just "whatever the code does."

A format with two implementations is a **real** format. The two implementations constrain each other — if they disagree, one of them (or the spec) is wrong and has to be fixed. Users can compare. Contributors can test against both. Interop becomes a property that can be tested, not just claimed.

This is the same dynamic as with any standard. HTML has meaning because it's implemented by Chrome AND Firefox AND Safari. PDF has meaning because it's implemented by Acrobat AND Preview AND a dozen others. If any of those formats had only one implementation, they'd be proprietary blobs.

## How rapp-installer became a hatcher

The rapp-installer project was the original native Python harness — a Flask app that loads agents from a directory, runs a Python process, serves a local chat UI. It predates the Virtual Brainstem.

Adding egg-compliance was conceptually simple:

1. Add an import endpoint that accepts a `.rapp.egg` JSON.
2. Parse the egg, validate against the schema.
3. Load the soul into the agent's system prompt.
4. Load the memory into the agent's memory store.
5. Resolve the tool list (fetch from RAR, from local files, from wherever the `source` URI points).
6. Start a chat session with the hatched daemon.

The whole thing was ~200 lines of new code, because the underlying agent system was already there. Egg-compliance is mostly a *loader*, not a rewrite of the core.

For export: mirror the import flow. Take the current daemon's soul, memory, and tool list; format as a v1 egg; write the JSON file.

## What broke

In the process of testing interop, we found:

**Mismatch #1: tool source resolution.** The Virtual Brainstem defaults to `rar://` for tools without an explicit source. rapp-installer defaulted to `file://` (it assumed local). An egg exported from one, imported into the other, had every tool resolve to the wrong place. Fix: the spec now says the default is `rar://`. Both implementations agreed.

**Mismatch #2: memory format.** The Virtual Brainstem structures memory as a flat list of strings. rapp-installer used a nested dict (facts, preferences, context as separate keys). The spec had *both* shapes documented as valid, which is a bug in the spec. We standardized on the nested dict; the Virtual Brainstem updated to emit that format.

**Mismatch #3: canonical SHA.** The Virtual Brainstem was computing the SHA over the egg JSON as-is (including any whitespace differences). rapp-installer computed over canonical serialized JSON (sorted keys, no whitespace). Two implementations looking at the same egg produced different SHAs. Fix: the spec says canonical serialization is required; the Virtual Brainstem now does the same.

Each of these mismatches was an honest bug — not philosophical disagreement, just the two implementations having slightly different assumptions that hadn't been exercised. The second hatcher surfaced them. They'd have festered for months without.

## What stayed working

Surprising (and heartening):

- **Soul loaded cleanly.** Both implementations handle long text blobs the same way.
- **Basic tool references (`rar://name`) resolved correctly.** The shared reference to the RAR registry Just Worked across both.
- **Metadata fields (name, author, created_at) round-tripped unchanged.** The JSON primitives are simple enough that nothing went wrong.

About 90% of an egg's content moved cleanly between the two hatchers. The 10% that broke was concentrated in subtle areas (memory shape, canonicalization, source resolution defaults). Exactly the kind of thing a second implementation catches.

## The broader pattern

There's a life cycle for formats:

**Phase 1: Single implementation.** The creator builds it. It works for them. Nobody else uses it.

**Phase 2: Second implementation.** Someone else (or another team) builds their own. Interop bugs surface. Spec gets tightened. Implementations converge.

**Phase 3: Multiple implementations.** A few more groups ship. Now the format is *substrate-stable* — no single implementation can break backwards compatibility without the ecosystem noticing and pushing back.

**Phase 4: Ubiquity.** The format is assumed. People stop asking "does X support the format?" and start asking "why not?"

We're at the end of Phase 1 / start of Phase 2 with `.rapp.egg`. The second hatcher moves us into Phase 2 formally. A third hatcher (maybe from the community) would push us toward Phase 3.

## Why I invested in the second hatcher

I could have done a lot of other things this week. Writing the second hatcher was several hours of work. Why this?

Because **the value of the format is the value of the ecosystem around it, and the ecosystem needs multiple implementations to grow.** Without the second hatcher, every new user of `.rapp.egg` would be a user of the Virtual Brainstem, which would make the "format" indistinguishable from "the brainstem's internal state format." That's a vendor lock-in I don't want to ship.

With two hatchers, users can pick. If the Virtual Brainstem disappears tomorrow, their eggs still work on rapp-installer. If rapp-installer disappears, their eggs still work on the brainstem. If a third hatcher ships, it inherits the compatibility.

This is the exact argument for open standards. They cost more to maintain than proprietary formats. They're worth it because they survive individual tools.

## What a third hatcher would look like

Anyone could build one. The bar is:

- Read JSON (any language)
- Validate against the v1 schema
- Load the soul into an LLM's system prompt
- Store the memory somewhere your daemon can retrieve it
- Resolve tool URIs (at minimum: `file://` and `rar://`)
- Return control to the user's interface

That's all. A minimal hatcher in Go, Rust, Elixir, or TypeScript would probably be 500-1000 lines. A weekend project for anyone comfortable with their language of choice.

If you want to build one, I'll link to it. I'd especially love to see:

- **A CLI hatcher** — `rapp-egg run my-daemon.rapp.egg` spawns a terminal chat
- **An iOS/Android app hatcher** — native mobile UX beats mobile Safari
- **A Slack/Discord bot hatcher** — the daemon lives in a channel
- **A server hatcher** — the daemon is an HTTP endpoint that other apps can talk to

Each of these is a different form factor for the same underlying daemon definition. The egg doesn't care; it just wants to be hatched.

## The lesson I'll carry forward

When you design a format, build two implementations before you publish the spec as "final." You don't know what's wrong with the spec until a second implementation forces you to find out. The interop bugs you find will always be surprising; the fixes will always be reasonable; the format you end up with will be better than the one you started with.

This is the old wisdom about RFCs — *"Rough consensus and running code."* Two pieces of running code force the rough consensus. One piece lets you live in your own fictions.

The Virtual Brainstem has a new sibling this week. The format is stronger for it.

---

**Related:**
- [Announcing `.rapp.egg` Spec v1](announcing-egg-spec-v1) — the format itself
- [The Harness Is the Room](harness-is-the-room) — what makes hatchers possible
- [Introducing the Virtual Brainstem](introducing-virtual-brainstem) — the first hatcher
