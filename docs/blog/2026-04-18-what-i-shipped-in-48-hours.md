---
layout: post
title: "What I Shipped in 48 Hours"
date: 2026-04-18 14:45:00 -0400
tags: [receipts, meta, process, ai-assisted]
---

The last 48 hours, in receipts.

**Blog posts shipped:** 20
**Twin platform drafts shipped:** 18 (X threads, LinkedIn posts, DEV.to articles, Matrix/Discord/HN announcements, Substack essay, newsletter issue)
**Working artifacts shipped:** 3 (CLI hatcher, YouTube Shorts player, Virtual Brainstem mobile UX fixes)
**New Python lines:** ~1,300
**New HTML lines:** ~500
**New documentation words:** ~45,000
**Spec updates:** 3 (memory shape, tool import conventions, canonical SHA field scope)
**Third-party infrastructure dependencies added:** 0

I'm writing this post partly to prove it happened and partly because the throughput is the thing worth remarking on. Two years ago this would have been a month of work, maybe more. Today it's a long weekend.

## What made it possible

Three things, compounded.

### 1. The AI that remembers me

Every session starts with the assistant reading its accumulated memory of me — my role, my voice, my architectural preferences, my recurring ideas, my writing tics I hate, my feedback from prior corrections. No warm-up, no re-explaining.

This saves roughly 30 minutes at the start of every session. Multiply by 8-10 sessions in 48 hours. That's the difference between "can't get traction" and "already rolling."

More importantly: the drafts the AI produces *sound like me*. I don't spend hours rewriting every paragraph to strip out the generic-tech-blogger register — the register is already wrong from the first draft, because the AI knows.

Full writeup: [Writing Blog Posts with an AI That Remembers](writing-blog-posts-with-an-ai-that-remembers).

### 2. The harness-sacred philosophy

Most of what I built in 48 hours ships as files, not as changes to infrastructure:

- CLI hatcher: one script, no changes to anything else
- YouTube Shorts player: one HTML file, no changes to anything else
- 20 blog posts: each one a file in `docs/blog/`, auto-rendered by the existing blog machinery
- 18 twin drafts: each one a file in `docs/twin/<platform>/`

Nothing required wiring changes. Nothing required schema migrations. Nothing required coordinating with other systems.

This is the payoff for the harness-sacred architecture [I wrote about earlier](harness-is-the-room). When every capability ships as a file, shipping-per-unit-time goes up and coordination-cost-per-ship goes down. You compound.

### 3. The static-first infrastructure

Everything I shipped lives on static hosting:

- Blog posts: GitHub Pages, no server
- Twin drafts: file in repo, rendered on demand
- Virtual Brainstem: one HTML file on Pages
- YouTube Shorts: one HTML file on Pages, videos from raw.githubusercontent.com
- CLI hatcher: git clone + run

Not a single backend was deployed, scaled, or debugged in these 48 hours. That alone would have consumed the whole window two years ago.

Full writeup: [Static JSON Is a Registry](static-json-is-a-registry).

## What I didn't do

To be honest about the trade-offs:

- I didn't do deep architectural work. The 48 hours was mostly content + small artifacts, not core platform changes.
- I didn't do any product research. No user interviews, no data analysis, no A/B testing.
- I didn't write tests for the new artifacts. The CLI hatcher has smoke tests (I verified it loads the seed egg correctly), but no pytest suite.
- I didn't polish the UX beyond functional. The Shorts player works; it doesn't look as polished as a production Shorts app.
- I didn't sleep a normal amount. To be clear.

Some of these are fine. Some need to be picked up soon. A tool without tests will bite me eventually.

## What I'd warn a friend about

If you're thinking about trying a similar sprint:

**Warning 1: Don't trust the AI for ideas.** The AI can draft posts I've already got an idea for. It cannot generate the idea. 20 posts in 48 hours required 20 nucleus-ideas I brought. Without that supply, the sprint is just AI slop.

**Warning 2: Cognitive fatigue is real.** By post 15, my quality judgment was degrading. I relied more heavily on the AI's drafts and did less personal editing. The last few posts are thinner than the first few.

**Warning 3: Coordination cost still exists.** Even with zero backend, there's context-switching between posts, drafts, artifacts, and communication. A well-organized context-management system (task list, memory, scratchpad files) was necessary.

**Warning 4: You might annoy your audience.** 20 blog posts in a weekend is unusual throughput. Some readers will appreciate the avalanche; some will unsubscribe. Matrix-shaped content is welcomed on Matrix; LinkedIn-shaped content is welcomed on LinkedIn; cross-posting everywhere at volume risks coming across as spam.

**Warning 5: Quality does drop with volume.** I stand behind most of what I wrote. A couple of posts are meaningfully weaker than they'd be if I'd had another day. Know which posts are your best and which are OK — don't stake your reputation on the OK ones.

## What the sprint enabled

The sprint ends. The artifacts stay. 48 hours from now, 72 hours from now, a year from now:

- 20 blog posts keep earning attention as they index, share, link-together
- The CLI hatcher is a permanent tool in the repo
- The Shorts player is a permanent surface that can accumulate content
- The Virtual Brainstem mobile UX is better forever
- The 18 twin drafts can be published over the next month at a natural cadence

Short-term throughput converted to long-term assets.

This is the pattern I like most about shipping in public. You do a lot of work, it goes out, and it keeps working. Nothing is lost to the sprint; everything is gained.

## The meta-point

Lots of people right now feel like AI has made software production faster — but they can't quite point at what they've shipped because of it. That's partly a real problem (it's easy to feel productive while producing nothing that ships).

This post is partly an attempt to turn the vibe into receipts. Here's what I produced. Here's what it cost. Here's what held me back. Here's what made it possible.

Your mileage will vary. Mine has never been this good.

---

**Related:**
- [On Shipping 23 Drafts in Two Days](on-shipping-23-drafts-in-two-days) — the earlier sprint
- [Writing Blog Posts with an AI That Remembers](writing-blog-posts-with-an-ai-that-remembers) — the memory layer
- [The Harness Is the Room](harness-is-the-room) — the architecture that enables this pace
