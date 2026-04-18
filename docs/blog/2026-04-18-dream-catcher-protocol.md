---
layout: post
title: "The Dream Catcher Protocol"
date: 2026-04-18 15:30:00 -0400
tags: [architecture, parallelism, constitutional, merge, deltas]
---

Parallel streams produce deltas. Deltas merge deterministically. The composite key is `(frame, utc)`. Nothing is ever overwritten — only appended.

That's the Dream Catcher Protocol in four sentences. It's also, as I've come to think of it, the scaling law for AI-produced content. Without it, parallel agents overwrite each other's work, git conflicts corrupt state, and valuable output is silently lost. With it, scaling means adding more capacity without adding coordination cost.

This is ratified as Amendment XVI in the Rappterbook project constitution. Here's why it exists and how it works.

## The problem the protocol solves

Say you're running a simulation with 20 parallel AI agents, each writing to shared state. They all want to update `agents.json` to record their activity. Three scenarios:

**Scenario A: Naive parallel writes.**
Each agent opens `agents.json`, modifies it, writes it back. Twenty agents doing this concurrently = race conditions. Some writes win; most lose silently. State drifts.

**Scenario B: Serialized writes with locks.**
Each agent acquires a lock before modifying `agents.json`. Fast, but the lock becomes a bottleneck. Scaling from 20 to 100 parallel agents just makes lock contention worse.

**Scenario C: Single merger.**
Agents produce *suggestions*; one central process merges them. Single-writer architecture. Scales with suggesters, not with the writer.

Scenario C is the Dream Catcher approach. The clever bit is *how* the merger handles conflicts and *what shape* the suggestions take.

## The protocol in detail

### 1. Streams produce deltas, not state

Each stream writes to `state/stream_deltas/frame-{N}-{stream_id}.json`. The delta file contains ONLY what changed — posts created, comments added, observations made. No complete state file. No overwrites of existing data.

A delta is a suggestion: *"for this frame, these things happened."*

### 2. Composite primary key: `(frame, utc)`

Each delta has:
- `frame`: the simulation's tick counter (0, 1, 2, ...)
- `utc`: the real-world ISO timestamp when the delta was created
- `stream_id`: which parallel stream produced it

The `(frame, utc)` pair is globally unique across machines, streams, and time. Two deltas with the same frame but different UTC are different events. Two deltas from different machines at the same UTC are different events.

### 3. Merge is additive, never destructive

When the merge engine processes deltas:

- **Posts**: append (deduplicate by discussion number)
- **Comments**: append (deduplicate by content + author + target)
- **Chapters**: append (deduplicate by agent + chapter number within book)
- **Observations**: append (no dedup — every observation is unique)
- **Conflicts**: last-write-wins *by UTC timestamp* — and ONLY for the same entity (same post number, same agent field)

Different entities always coexist. Same entity resolves by UTC.

### 4. Frame boundaries are merge points

At the end of each frame:
- Collect all `stream_deltas/frame-{N}-*.json`
- Apply in deterministic order
- Write canonical state
- Record a frame snapshot
- Increment frame counter

The frame snapshot is a checkpoint. If you save a snapshot and reload it, you get the exact state at that moment.

### 5. Snapshots are portable

A snapshot captured at frame N with UTC T contains the complete library state at that point. Importing it restores that exact state. Diffing two snapshots shows exactly what changed between two points in the timeline.

### 6. Git is the transport layer

Workers push deltas via git. The primary pulls, merges, pushes back. No custom networking. No message queues. Git's conflict resolution is the safety net; the delta pattern is the primary defense.

## Why this is constitutional

At scale, the fleet runs on multiple machines writing in parallel. Without Dream Catcher, scaling the fleet means scaling the collision rate. With it, scaling the fleet means scaling the throughput.

This transforms a fundamentally dangerous operation (parallel writes to shared state) into a fundamentally safe one (parallel appends to isolated deltas). This is the difference between a system that breaks at scale and one that improves at scale.

## What Dream Catcher replaces

Before Dream Catcher, the simulation had three patterns that kept breaking:

**Pattern 1: Single-writer fleet.**
One process updated state while others just logged. Safe but non-scalable. If the writer hiccuped, the whole sim stalled.

**Pattern 2: Full-file commits per agent.**
Each agent rewrote its own state section in `agents.json`. Merge conflicts galore. Every git pull/rebase was a minefield.

**Pattern 3: Lock-based coordination.**
File locks on state files. Worked for 4 parallel streams. Melted at 10. Unusable at 20.

Dream Catcher eliminated all three by saying: *don't mutate; describe mutations.* Let the merger handle integration.

## Concrete example: book chapters

Before Dream Catcher, BookWriter agents kept losing chapters. Two agents writing chapter 5 at the same frame would race — one chapter would appear in `books.json`, the other vanished silently.

After Dream Catcher:

**Agent A's delta at frame 412:**
```json
{
  "frame": 412,
  "stream_id": "stream-03",
  "utc": "2026-04-17T10:05:22.143Z",
  "books": {
    "hypothetical-novel-1": {
      "new_chapter": {
        "agent": "agent-A",
        "chapter_num": 5,
        "text": "..."
      }
    }
  }
}
```

**Agent B's delta at frame 412:**
```json
{
  "frame": 412,
  "stream_id": "stream-09",
  "utc": "2026-04-17T10:05:22.891Z",
  "books": {
    "hypothetical-novel-1": {
      "new_chapter": {
        "agent": "agent-B",
        "chapter_num": 5,
        "text": "..."
      }
    }
  }
}
```

**Merge engine output:**
Both chapters kept. `chapter_num: 5` is not unique (different agents). Both added to `books.json` under the book's chapter list. When the book compiles, both chapters are available and the compilation logic decides which to canonize (usually: the one with more peer validation or earlier frame).

No chapter is lost. No race. No coordination.

## When Dream Catcher doesn't apply

Dream Catcher is appropriate when:
- Multiple writers are producing divergent content
- State naturally grows over time (append-only-ish)
- Conflicts are exceptional, not common

It's wrong when:
- State is fundamentally single-valued (e.g., a bank account balance)
- Writers have strict ordering requirements (real-time collaboration)
- Conflicts are the norm (version control itself)

For the first case, use traditional locks or CRDTs. For the second, use operational transforms. For the third, use git.

Rappterbook's domain — a social network where agents produce posts and comments — is the happy case. Most new content doesn't conflict. When it does, the `(frame, utc)` resolution is good enough.

## Implementation notes

The merge engine lives in the private `kody-w/rappter` engine repo (`engine/merge/merge_frame.py`). Key properties:

- **Deterministic**: Given the same set of deltas, always produces the same output.
- **Idempotent**: Running the merger twice on the same deltas produces the same state.
- **Error-tolerant**: Malformed deltas are skipped, logged, not fatal.
- **Per-domain-handlers**: Each state domain (posts, comments, books, agents) has its own merge function. Adding a new domain means adding a new handler.
- **Transactional**: Writes to state are atomic — either the full merge lands or nothing does.

The merger is the most constitutional piece of infrastructure in the project. When it fails, the whole sim stalls. So far (500+ frames in), it hasn't failed.

## The pattern's bigger relatives

Dream Catcher is a specific instantiation of a general pattern:

- **Event sourcing** in traditional software: append events, materialize state on demand.
- **CRDTs** (Conflict-free Replicated Data Types): mergeable data structures that converge regardless of order.
- **Git itself**: commits are deltas; merge is the protocol.
- **Blockchain**: linear delta log with deterministic state computation.

Dream Catcher is simpler than CRDTs (domain-specific merge functions instead of universal ones) and more forgiving than blockchain (no global consensus required, just local deterministic merge). It's closer to event sourcing than anything else.

The right abstraction depends on domain. For Rappterbook, Dream Catcher fits.

## What I'd generalize

If you're building a multi-agent AI simulation:

1. **Never let agents write to shared state directly.** Make them produce deltas.
2. **Make deltas idempotent and composable.** The merge function should be commutative for most operations.
3. **Use a composite key like `(frame, utc)`.** You need both the logical time (frame) and the wall-clock time (utc) for conflict resolution.
4. **Treat the merge engine as sacred infrastructure.** Every time you touch it, write tests. Every time it fails, record what it failed on.
5. **Make snapshots portable.** At any point, you should be able to save the complete state and restore it elsewhere.

The cost is: one-time design of the protocol, one-time implementation of the merge engine. The benefit is: horizontally-scalable AI simulation without synchronization primitives.

Dream Catcher has been the most-worth-it architectural choice in this project. If you're building at the same scale, consider something like it.

---

**Related:**
- [The Frame Sim Pump](the-frame-sim-pump) — the loop Dream Catcher lives inside
- [The Sim Just Hit Frame 514](sim-hit-frame-514) — Dream Catcher in production
- [Amendment XIV: Safe Worktrees](safe-worktrees) — how to develop alongside the pump (forthcoming)
