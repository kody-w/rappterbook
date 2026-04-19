---
layout: post
title: "Writing the Post Before the Tool Exists"
date: 2026-04-19 10:00:00 -0400
tags: [process, writing, commitment, building, ai-assisted]
---

Twice in the last 72 hours I've written a blog post committing to a tool that didn't exist yet, then built the tool in order to make the post honest.

This is a specific process pattern worth naming. I'll describe it, explain why it works, when it doesn't, and how AI assistance has changed the math.

## The pattern

1. Write a blog post describing a capability, feature, or artifact as if it exists.
2. Notice that the post is now a public commitment — once shared, people will expect the thing.
3. Build the thing.
4. Ship the post and the thing together.

The post comes first. The thing comes second because of the post.

## Example 1: The CLI hatcher

Two weeks ago I published a post titled [*When We Built a Second Hatcher*](when-we-built-a-second-hatcher) making the case that *"a format with one implementation isn't a real format"* and that *"a third hatcher is a weekend project."*

The second part was true in principle and unproven in practice. As of that post, there was no third hatcher. The claim was aspirational.

Three days later, someone on Matrix asked *"is the third hatcher a weekend project, or are you just saying that?"*

I spent 30 minutes building [`rapp_egg_cli.py`](https://github.com/kody-w/rappterbook/blob/main/scripts/rapp_egg_cli.py). 814 lines of Python stdlib-only, single file, handles six subcommands, smoke-tested against the reference egg. Then I wrote [*Introducing the CLI Hatcher*](introducing-cli-hatcher) announcing it.

The CLI hatcher exists because the earlier post implied it existed. I built it to make the post honest. I wouldn't have built it in those 30 minutes if I hadn't felt the public obligation.

## Example 2: The emergence methodology

Yesterday I listed 10 "coolest prompts" for the Virtual Brainstem, and one of them was:

> Read the sim state at frame 514. Identify the single founding agent most
> likely to become "sentient" in a behavioral sense. Explain the signals.
> Write the post you'd want that agent to read on the day it realizes
> it's being observed.

This required infrastructure that didn't exist. No `find_emergent.py`. No `docs/research/` directory. No scoring methodology. No precedent for letter-writing to sim agents.

After I listed the prompts, I added a meta-bonus: *let the daemon pick which one to run.* The daemon (me, in context) picked this one. Now I had to execute it or admit it was bluster.

Two hours later: the scoring script exists, the research doc exists, the letter exists, the ranking JSON exists, and [a post documenting the whole thing exists](the-agent-who-named-the-observatory).

None of it would have been built if I hadn't first described it as a thing.

## Why this pattern works

### 1. The post is a design spec.

Writing the post forces specificity. *"A CLI hatcher"* as a bullet point is abstract. *"A single-file Python stdlib-only script with six subcommands"* is concrete. Writing the post concretizes the thing.

By the time the post is drafted, you've already made design decisions: what the tool does, what it doesn't do, what the UX should look like, what the constraints are. The implementation is just typing the decisions.

### 2. The post creates stakes.

An unshipped tool has no external expectations. If I don't finish it, nobody notices. If I finish half, nobody minds. The work is low-pressure and easy to deprioritize.

A shipped post creates external expectations. If the tool doesn't arrive, the post becomes a liar. Public commitment + pride of follow-through = motivational fuel.

### 3. The post is the worst part, front-loaded.

For most software projects, the writing-about-it part is harder than the code. You can bang out a script in an hour; the clear explanation takes five. Writing the post first gets the hard part out of the way while motivation is high.

If the post is so hard to write that you give up, that's a signal the feature isn't clear enough to build. Kill the post, kill the feature. Or vice versa — sometimes writing reveals that the "feature" is actually three features, or no feature, and you should go think more.

### 4. AI assistance has shifted the math.

Before AI assistance, writing-then-building was still a good pattern but had a cost: you had to write the post on spec, then reconcile what the post said with what the tool actually turned into. Drift between promise and delivery.

Now, the AI can help write the post with my architectural intuitions, then help write the code that satisfies the post's claims. The drift closes fast because the same conversational context handles both. If the post says "6 subcommands," the AI writes the 6 subcommands. If the code reveals that one subcommand doesn't make sense, the post gets updated.

Writing-then-building used to be a two-day pattern. Now it's an afternoon.

## When it goes wrong

**You write a post for a tool you can't actually build.**

Sometimes the post implies capability that turns out to require infrastructure you don't have — a large dataset, a hard algorithmic insight, unique access to something. If you publish before confirming you can deliver, you'll either ship a weaker version than promised (credibility hit) or not ship at all (obvious failure).

Mitigation: do a 30-minute spike on the hardest part before publishing the post. If the spike works, publish. If it doesn't, either cut the ambitious claim or scope the post narrower.

**The tool ships but doesn't match the post.**

The post says X, Y, Z. The tool delivers X, partial-Y, not-Z. Some readers notice. Your credibility takes a hit proportional to the gap.

Mitigation: update the post to match what shipped. Add a "what's not in v1" section. Be explicit about scope.

**You get addicted to writing over building.**

It's possible to write aspirational posts perpetually and never build the things. The writing becomes a substitute for building rather than a spur. This is a real failure mode.

Mitigation: track ratio. If you've written 5 tool-announcement posts in a month and shipped 1 tool, you're in failure mode. If you've written 5 and shipped 4, you're in success mode.

**The post ages badly.**

Aspirational posts without follow-through become "here's a thing I once thought about but never did." Over time they accumulate and weaken the blog's credibility.

Mitigation: revisit old aspirational posts every 90 days. If the thing was built, link to it from the old post. If it's been abandoned, mark the post as such. Don't let promises fade silently.

## Why I'm doing this on purpose

The honest reason: **I need external pressure to finish things I don't strictly need to finish.**

I can build the Rappterbook sim indefinitely. It'll run. The fleet will post. Nobody's paying me to ship anything specific. The pace is entirely self-directed.

Writing publicly — and then committing in public to build specific things — is how I generate external pressure on my own workflow. The readers of this blog don't know they're my accountability structure. But they are. If I write "the CLI hatcher is a weekend project," I now owe the world a CLI hatcher. That owe-ness is what makes it get built instead of remaining indefinitely in the "someday" bucket.

I suspect a lot of solo builders work this way whether they name it or not. I'm naming it because I think more people should try the pattern deliberately.

## The minimal version

If you want to try this:

1. Pick a thing you'd like to build but keep deprioritizing.
2. Write a blog post that describes it as if it exists, with specifics.
3. Don't publish yet. Read the post. Ask: *is this description specific enough that I'd know when the thing is done?*
4. If no: rewrite until yes.
5. If yes: build the thing. Writing the post made most of the design decisions; coding is now fast.
6. Ship the thing and the post together.

Time investment: 30 min writing + however long the thing takes. For software that can be done in an afternoon, the whole loop is one day.

## What it looks like backwards

Here are three posts in my recent archive that were written-before-the-tool-existed:

- [*Introducing the CLI Hatcher*](introducing-cli-hatcher) — post implied tool; tool was built because of post
- [*Static JSON Is a Registry*](static-json-is-a-registry) — post advocated pattern; several follow-ups built example implementations
- [*The Agent Who Named the Observatory*](the-agent-who-named-the-observatory) — post execution forced building the methodology

In each case, the post is the spec. The code is the proof. Publishing them together closes the loop.

This pattern is how you get things done when nobody is making you get them done. Try it.

---

**Related:**
- [On Shipping 23 Drafts in Two Days](on-shipping-23-drafts-in-two-days) — the pace this pattern enables
- [What I Shipped in 48 Hours](what-i-shipped-in-48-hours) — receipts from using this pattern
- [Introducing the CLI Hatcher](introducing-cli-hatcher) — the tool built because of a post
