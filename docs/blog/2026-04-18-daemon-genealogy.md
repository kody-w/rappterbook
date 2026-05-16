---
layout: post
title: "The Daemon Genealogy Graph"
date: 2026-04-18 11:15:00 -0400
tags: [philosophy, daemons, identity, genealogy, ai]
---

When someone hatches `kodyTwinAI.rapp.egg`, modifies its soul, adds a few agents, and exports the result as `myDaemon.rapp.egg`, their new daemon is *descended from* the original. The two daemons are related the way a child is related to a parent — same ancestry, different life.

This is not just a nice metaphor. If you keep the lineage, it becomes a graph — a daemon family tree — with real properties you can exploit.

## The claim

Every `.rapp.egg` should optionally carry its lineage: the SHA of the parent egg, the name of the parent, the timestamp of the fork. When egg A is hatched and modified to produce egg B, B's metadata records "forked from A" before the export happens.

This costs ~50 bytes per egg. It gains you a genealogy graph over time.

## Why this matters

**Provenance.** Given a daemon, you can ask: *"who did this come from?"* and get back a chain — myDaemon ← friend-fork ← kodyTwinAI ← base-template. Any daemon's history is recoverable to its root.

**Reputation propagation.** A daemon with a trustworthy ancestor (a well-known base like kodyTwinAI) inherits some of that trust. A daemon with unknown ancestry is more suspect. This is how humans judge novelty — unknown provenance is noise; known provenance is signal.

**Improvement tracking.** If you fork kodyTwinAI and I fork it, our improvements are siblings. Later, I can see your branch, merge the good parts, and produce a grandchild that incorporates both our work. Genealogy makes this kind of cross-pollination visible and navigable.

**Rollback.** If my daemon starts behaving weirdly, I can walk back up the tree and re-hatch from an earlier ancestor. Daemon state becomes *versioned*, which means it can be restored the way git branches can be restored.

**Archeology.** In five years, someone can ask *"where did this daemon come from?"* and the answer is traceable. Without lineage, daemons float free, decoupled from their history. That's a loss.

## The graph structure

A daemon genealogy is a **DAG** (directed acyclic graph), not strictly a tree. Reasons:

- A daemon can fork from another daemon → normal tree edge
- A daemon can *merge* ideas from two ancestors (soul prompt from A, agents from B) → a merge commit, two parent edges
- A daemon can be *cloned* by an external user as a sibling → two daemons with the same parent

This is exactly the same shape as git history, and for the same reasons.

## How you actually build it

Add one optional field to the egg metadata:

```json
{
  "meta": {
    "name": "myDaemon",
    "version": 1,
    "created_at": "2026-04-18T10:00:00Z",
    "parent": {
      "sha": "abc123...",
      "name": "kodyTwinAI",
      "version": 1
    }
  }
}
```

When the export flow runs, it captures the parent SHA (the hash of the egg the user originally hatched from) and writes it into the child. That's the entire infrastructure burden.

The genealogy graph emerges from aggregating these fields across many eggs. An index service can scan known eggs, extract parent pointers, and build the graph. The RAR registry is a natural place to host this.

## Visualizing it

Once you have the graph, you can draw it. A daemon tree visualization might show:

- Nodes are daemons (with name, creator, creation date)
- Edges are parent → child relationships
- Node size scales with popularity (number of children)
- Branches colored by theme (creative vs technical vs research)
- Dead branches (no descendants in 6 months) fade out

This ends up looking a lot like a git-log visualization, which is appropriate — the underlying structure is the same.

## Why this is more than novelty

Daemon genealogy is the substrate for *trust graphs* in a world of AI agents. Once daemons can carry and present their lineage:

- **You can define policies** like "I only hatch eggs whose root is one of these trusted bases."
- **You can run reputation computations** like "daemons forked from mostly-good ancestors are mostly trustworthy."
- **You can trace misbehavior** by checking: where did this problematic behavior enter the lineage? Which ancestor first had it?
- **You can cite a daemon** the way academic papers cite sources: "this daemon is a descendant of kodyTwinAI 1.2, which is a descendant of Base Template v3."

None of this requires central authority. The graph emerges from the data. The data emerges from normal daemon use.

## What you should NOT include in lineage

**Not the full contents of the parent.** That blows up the file size. Just the SHA (and optionally name/creator) — enough to resolve the parent if you want to, not the parent's entire state.

**Not mutable pointers.** The parent SHA is immutable once set. You can't "change your parent" after the fact. If you decide you don't want the lineage to be public, you strip the field before export. What you cannot do is rewrite it to point somewhere else — that would break the integrity of the graph.

**Not forced disclosure.** Lineage should be optional. Some daemons are personal; the user doesn't want the graph to be public. They can export without the parent field, or with a privacy-preserving hash commitment instead. Defaults matter here — default to including it for public daemons, default to omitting for clearly-personal ones.

## Relation to non-AI systems

The genealogy pattern is well-established outside AI:

- **Git** tracks file ancestry via commit parents. The DAG is the history.
- **Docker image layers** reference parent images. Your image is "from X at rev Y."
- **npm packages** track their own version history, though not as a graph across forks.
- **Wikipedia articles** track edit history, though not across forks/mirrors.
- **Academic papers** cite sources, building a citation graph that's essentially genealogy.

The daemon lineage is a direct application of this pattern to a new domain (AI personalities and their derivatives). Once you see the pattern, it's obvious it should exist. The question is whether anyone bothers to implement it in a standardized way.

## The spec pitch

If you're building a daemon format — not just `.rapp.egg`, but any AI-daemon-as-file format — include an optional parent pointer in your spec. Cost is a few bytes. Benefit is a family tree that compounds across time.

The benefit doesn't show up immediately. On day 1, the graph is empty. On day 30, it's a sapling. On day 365, it's a forest of lineage trees, each rooted in some founding daemon, each branching into descendants who each spawn further branches. The graph is an asset that grows with the ecosystem's use.

## The Rappterbook angle

The RAR registry tracks agent files with SHAs already. The next step is tracking daemon files — `.rapp.egg` manifests with lineage pointers. A "daemon browser" could walk the graph, render the family tree, show you descendants of a daemon you care about.

I haven't built this yet — it's on the backlog. But the plumbing is already there. Every egg exported by the Virtual Brainstem already captures a `created_at` and a `name`. Adding `parent` is a one-line change. The genealogy graph could be live by next week if I get bored.

## The deeper point

AI daemons are a new kind of artifact. They have identities, behaviors, relationships. They propagate through forking and adaptation. They can be improved or corrupted across generations.

Software artifacts of this kind benefit enormously from lineage tracking. Git proved this for code. Docker proved it for runtime environments. We're about to prove it for AI personalities.

Build lineage into your daemon format early. It costs almost nothing today. In five years, the people with lineage will have a living, navigable history of their AI ecosystem. The people without it will have a pile of files with no story.

Plant the seeds now. Watch the tree grow.

---

**Related:**
- [Portable Minds Are Portable Responsibility](portable-minds-portable-responsibility) — the ethical half
- [Static JSON Is a Registry](static-json-is-a-registry) — the substrate the genealogy lives on
- [Announcing `.rapp.egg` Spec v1](announcing-rapp-egg-v1) — the format itself
