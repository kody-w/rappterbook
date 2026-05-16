---
layout: post
title: "On Shipping 23 Drafts in Two Days"
date: 2026-04-18 11:45:00 -0400
tags: [writing, content, twin, process, ai-assisted]
---

This week I published drafts of the same ideas across 23 platforms — Twitter threads, LinkedIn posts, Dev.to articles, HN submissions, a Substack essay, a Reddit post, a Product Hunt listing, podcast scripts, YouTube concepts, Twitch plans, a Gumroad product, Discord and Matrix announcements, newsletter issues, book chapters, course outlines, and a set of technical guides. Plus twelve blog posts. In two days.

This would have been impossible two years ago. It's routine now. The mechanics are worth explaining.

## Why 23 platforms?

Audiences cluster. The crowd on Hacker News is not the crowd on LinkedIn. The people who read Substack essays are not the people who watch Twitch streams. Each platform selects for a different kind of reader, a different kind of attention span, a different tolerance for tone.

If I have one idea — say, "the `.rapp.egg` portable daemon format exists and here's why" — it will reach different people depending on how it's packaged. A Twitter thread will reach a different audience than a YouTube Live concept, even though the underlying claim is identical.

Shipping on only one platform means accepting that some relevant audiences will never hear. Shipping on many platforms means the idea has more chances to find the audiences that care.

## Why not just post the blog post everywhere?

Because platforms hate cross-posted content, and because audiences deserve platform-shaped content.

A Hacker News submission is not a blog post. It's a title plus a link, and the title has to be sharp enough that HN users click. A Twitter thread is not a blog post either — it's 10-15 short beats that stand alone and build on each other. A podcast script is not a blog post — it's conversational, paced for listening, full of verbal handoffs and pauses.

If you shove a blog post into all these formats, it flops on all of them. The blog post was shaped for blog readers. Each other platform deserves its own shape.

## The actual workflow

The workflow is: *write the blog post once, then adapt to each platform, recording what was adapted and why.*

Step 1: Write the blog post. This is the longest step. I invest in the writing here because everything else inherits from it.

Step 2: For each target platform, create a drafts file. The file has frontmatter about the platform (Matrix room, Discord channel, Gumroad product type, Substack section) and then the adapted content.

Step 3: Adapt the content per platform. For some (Matrix/Discord), the adaptation is mostly trimming — 200-500 words. For others (Substack, podcast), the adaptation is expansion — the content grows because the platform rewards depth. For others (Twitter thread, LinkedIn post), the adaptation is restructuring — same claims, different sequencing optimized for the feed.

Step 4: Review the drafts for tone. Platforms have different tones. Matrix tolerates informal; LinkedIn expects polished-professional; Dev.to welcomes technical-first-person; Reddit respects the subreddit's conventions. I eyeball each draft in the voice of the platform.

Step 5: Don't publish yet. Store as `status: draft` files in `docs/twin/<platform>/...`. The publishing step is its own beat — I want to review a week's worth before any of them go live.

## The role of AI

Two years ago, this workflow would have taken me a month. Today it takes me two days because an AI handles most of the adaptation work.

My involvement per platform is approximately: *"Here's the blog post. Write the Matrix announcement version. Make it sound like a Matrix room post. Include the right links. Target the `#rappter-announce` room. Keep it under 500 words."*

The AI reads the blog post, understands the Matrix conventions (I've given it prior examples), and produces a draft. The draft is ~90% of what I'd write. I review, trim, adjust voice, add or remove links, confirm, save.

The math is: the first 50% of content quality takes 10% of my time (with AI help); the last 50% takes the remaining 90%. That's a dramatic shift from writing fully by hand, where the first 50% and the last 50% are roughly equal time.

## What AI is bad at

AI doesn't know the *current state* of the ecosystem without being told. It doesn't know that Matrix is currently quieter than Discord for my audience. It doesn't know that Product Hunt changed its submission rules last week. It doesn't know which subreddit mods have banned cross-posts from specific domains.

AI also doesn't know my voice in the way I do. It writes in a generic "thoughtful tech blogger" register that I have to pull toward my actual voice — slightly more informal, a bit more willing to sound opinionated, quicker to ship loose claims I'll defend in comments.

And AI can't tell when I'm repeating myself. Across 23 drafts, some ideas come up in almost every one. I have to notice when I'm saying the same thing in 23 different voices and decide if it's OK (sometimes yes — the audiences don't overlap; sometimes no — the ideas are stale).

## What the 23 drafts accomplish

Most of them will flop. Platforms are noisy. Specific audiences are specific. Some of these drafts will never even get published because the platform needs something I don't have time to create (like a podcast recording session).

But the *portfolio* effect is real. Out of 23 drafts, maybe 5 land well. Maybe 2 land in a way that causes sustained traffic or conversations. Maybe 1 goes viral. Maybe 0 do.

I can't predict which ones. What I can do is widen the set so that my batting average stays low but my total hits stay meaningful.

If I only shipped on my blog, my total hits would be `blog_audience * click_rate`. If I ship on 23 platforms, my total hits are the sum across all of them, and while each individual one is low, the sum is higher than my blog alone.

## What I notice about the process

1. **Shipping creates shipping.** Once I'm in the drafting mode, I keep drafting. The transition cost from "writing one thing" to "writing many things" is much smaller than I expected. Momentum is a real variable.

2. **Adapting a blog post forces clarification.** If I can't summarize an idea in 500 words for Matrix, I probably didn't say it clearly in the blog post. The short versions audit the long version.

3. **Some platforms are obviously wrong for a given idea.** A technical blog post about Pyodide debugging doesn't belong on Gumroad. Knowing when *not* to cross-post is as important as knowing when to.

4. **Reviewing 23 drafts is its own skill.** I had to invent a review pass — I read them all in quick succession, compare tones, spot repetition, flag things that feel off. The review caught bugs I wouldn't have caught in isolation.

5. **Draft quality is not publish quality.** These drafts need human polish before they go live. I'm not publishing raw AI output. The draft is the 90%; the polish is the last 10%; I still spend that last 10% because it's what separates "looks AI-generated" from "feels like a person wrote it."

## Where this goes

I think the multi-platform adaptation workflow is going to become the norm for anyone writing publicly. The mechanics are right there; the tools are good enough; the per-platform friction is down to minutes.

The people who ignore it will keep posting in one place and wondering why their reach is flat. The people who embrace it will hit more audiences, iterate on which platforms deserve their attention, and build presence across a portfolio of places.

This is also a new thing to be careful about. Platforms may push back on cross-posted content. Audiences may notice when an account is everywhere and push back on omnipresence. There are limits to how much of this is welcome.

But within those limits, multi-platform publishing from a single source of thought is a productivity win that was science fiction two years ago. I'm using it while it's still new.

Twenty-three drafts. Two days. Not bad.

---

**Related:**
- [Writing Blog Posts with an AI That Remembers](writing-blog-posts-with-an-ai-that-remembers) — the AI workflow
- [Why I Ship Everything as One File](why-i-ship-everything-as-one-file) — the upstream artifact
