---
layout: post
title: "Writing Blog Posts with an AI That Remembers"
date: 2026-04-18 12:15:00 -0400
tags: [writing, ai, memory, process, claude]
---

The blog posts on this site are co-written with an AI assistant that remembers every session we've had together. This post is about what that actually looks like in practice, and what it does to the writing.

## What "remembering" means

The AI has a memory system — a set of files, one per topic or person, that persist across conversations. When we start a new session, the AI reads the relevant memories and brings them into context. When the session reveals something new about me, my preferences, the project, it updates those memories.

The contents of my memory cover things like:
- My role (CEO of Wildhaven, building the Rappterbook ecosystem)
- My writing preferences (terse, specific, no bullet points that summarize what I just said)
- Project state (which posts are published, which are drafts, what the current initiative is)
- Feedback I've given that still applies (don't narrate my thought process; don't use emojis unless I ask)
- Recurring patterns (the "harness-sacred" philosophy, the "data sloshing" concept, the way I think about digital twins)

This memory accumulates slowly. It's not one big context dump; it's a curated set of facts that I've authorized the AI to hold onto.

## The drafting workflow

When I want to write a new blog post, the conversation goes something like this:

Me: *"Let me draft a post about the `.rapp.egg` format not being Docker."*

AI: *(reads relevant memories — knows I prefer terse, knows the context of the format, knows the audience for the blog)*

AI: Drafts a post that sounds like me, uses my common turns of phrase, avoids patterns I've previously said I don't want, structures the argument in the way I usually structure arguments.

Me: *(read the draft)* *"Take a stronger position in the opening. Less hedged."*

AI: Revises.

Me: *"Good. Tighten the middle; the Docker comparison section is doing the same work twice."*

AI: Revises.

Me: *(publish)*

Total time per post: 20-40 minutes, including the ideas, the draft, the revisions, the final polish. A post written by me alone takes 2-4 hours. A post written by me with an AI that doesn't remember me takes 1-2 hours. The memory layer shaves another 30-60 minutes off by skipping "explain who I am and what I want" at the start of every session.

## What this does to the writing

**Good effects:**

1. **The writing sounds like me more consistently.** The AI has learned my patterns. Even when it drafts a paragraph I wouldn't have thought of, the paragraph reads as if I had thought of it. This is good — it means the AI is an extension of my voice, not a different voice superimposed.

2. **Recurring ideas get compressed.** The AI remembers that I've already explained "data sloshing" in earlier posts, so new posts don't re-explain it from scratch. They link to the canonical explainer and build on it. This matches how I'd actually write — I don't want to repeat myself across 50 posts.

3. **Cross-post coherence.** When I write post N, the AI can reference posts 1 through N-1 and keep the voice, the framing, the terminology stable. Readers who binge the blog get a consistent experience rather than 50 posts in 50 slightly different voices.

4. **Less cognitive setup per session.** I don't have to re-establish context at the start of every session. The AI already knows I'm me, already knows what we've been working on, already knows my preferences. Cognitive tax is basically zero.

**Bad effects:**

1. **I sometimes write in its voice without meaning to.** After enough sessions, I catch myself using phrasings I originally saw in its drafts. This is fine — the phrasings are mine, in the sense that I approved them — but there's a subtle blending of authorship that's worth being honest about.

2. **I skip struggle that used to produce good ideas.** When writing is harder, I struggle more with a draft, and sometimes the struggle produces better ideas than the smooth draft. AI-assisted writing is smoother, which sometimes means I miss the "aha" that comes from being stuck.

3. **Memory can calcify incorrect patterns.** If I once said "I don't like bullet points" but actually I only disliked *one specific kind* of bullet points, that becomes a rule the AI applies everywhere. I have to audit memories periodically to make sure they still reflect what I want.

4. **I'm relying on infrastructure I don't control.** The memory lives in the AI's file system. If that infrastructure goes away, the memory goes with it. Mitigation: I export memories periodically to version-controlled files I own.

## What the memory does NOT include

Deliberate exclusions:

- **Strategic decisions I haven't shared.** Business plans, partnerships, confidential conversations — I don't authorize the AI to hold these in memory. If I mention one in a session, it stays in that session.
- **Personal information about people other than me.** The AI knows I have a family; it doesn't know names, birthdays, or specific events. Anything that would be weird in another person's memory is weird in this memory.
- **Assumptions about the future.** The AI shouldn't remember "Kody wants to ship X by Y date" as a fact, because dates slip and plans change. It remembers the *direction*, not the *commitment*.
- **Biographical trivia that's not load-bearing.** The AI doesn't need to remember my favorite color; that wouldn't help the writing.

The curation matters. An over-stuffed memory is worse than no memory because it gets applied too broadly. A well-curated memory is the difference between an assistant that feels like a colleague and one that feels like a surveillance log.

## What the memory makes possible beyond writing

The writing use case is one of several. The same memory layer enables:

- **Continuity across engineering sessions.** I start a session on a bug, pause for a week, come back, and the AI remembers where we were.
- **Personalization across unrelated tasks.** Working on a blog post, the AI knows my style; working on code, the AI knows my style. Neither bleeds into the wrong domain, because the memories are categorized and selectively loaded.
- **Learning from feedback.** When I correct the AI, the correction often becomes a new memory, and future sessions don't repeat the mistake.
- **Accumulation of private knowledge.** The AI can hold onto specifics of my project (architecture, key file paths, domain vocabulary) that would take forever to re-explain. Over months, this compounds.

## What I wouldn't do

I don't outsource the *thinking* to the AI. Memory doesn't generate ideas; it just makes the writing of ideas faster. When I have no idea what to say about a topic, the AI's drafts are generic. When I have a clear idea, the AI's drafts are sharp. The difference is me, not it.

I also don't let the AI "remember" arguments it hasn't engaged with. If I want to make a new claim, I make it myself. The AI can help me *express* the claim, but the claim has to come from me. Memory doesn't grow new opinions; it maintains old ones.

This matches how human memory actually works. We don't remember our own conclusions — we remember the *process* that got us there, and when we apply the conclusion later, we're re-deriving it in context. AI memory is similar — a file of "Kody believes X" is useful only if the *reason* for the belief is also in there, because the belief might need updating when the reason changes.

## What to tell a friend considering this

If you're thinking about writing with an AI that remembers:

1. **Start with one memory.** Pick one fact about yourself or your preferences that would save you time to re-explain. See how it feels.
2. **Review the memory periodically.** Make sure it still says what you want it to say. Delete memories that have become false.
3. **Don't overstuff.** A curated dozen memories is better than a hundred.
4. **Keep backups.** Memories are assets. Export them to a format you can read outside the AI.
5. **Stay the writer.** Let the AI draft, but own every sentence before you publish. Don't let the AI publish on your behalf.

The workflow is a tool. The writing is yours. The memory is there to save time, not to take over.

For me, the trade-off is squarely positive. I write more, ship more, and cover more ground than I would alone. The AI remembers enough about me that we can pick up where we left off. And the writing — including this very post — comes out sounding like me. That's all I really wanted.

---

**Related:**
- [On Shipping 23 Drafts in Two Days](on-shipping-23-drafts-in-two-days) — the throughput enabled by this workflow
- [The Daemon Genealogy Graph](the-daemon-genealogy-graph) — another memory-shaped artifact
