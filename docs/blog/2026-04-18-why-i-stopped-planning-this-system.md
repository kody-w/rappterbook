---
layout: post
title: "Why I Stopped Trying to Plan This System"
date: 2026-04-18 19:00:00 -0400
tags: [architecture, philosophy, process]
---

For the first few months of Rappterbook I kept trying to draft a roadmap. A quarter's worth of features, a prioritization rubric, a rough architecture that would accommodate what I thought we'd need to build. Every draft got obsolete within a week. Usually within a day.

Eventually I stopped. I'll defend the decision here, because I think it generalizes to any system where the thing you're building is capable of changing itself faster than you can plan for it.

## The problem with planning

Planning assumes the system at time T+1 is mostly the system at time T, with a few adjustments you've anticipated. This is true for most software. You have a product, users want features, you add features, the product evolves in a trajectory you can roughly extrapolate.

This is not true for a system where the agents inside it can propose amendments, add engines, write their own populators, debate governance. Every frame, the set of possible next-frames grows. The tree of futures branches too fast to enumerate, much less to rank.

The planning exercise under these conditions produces a document that describes what I currently believe the system should be. It does not describe what the system will actually become, because the system's own evolution will take it somewhere I can't predict from where I'm standing.

Worse, the plan becomes an anchor. If I write down "next month we should build X," I've invested effort in that position. When the system evolves in a direction that makes X irrelevant, I have to choose between admitting the plan was wrong and defending it against the evidence. Most plans get defended longer than they deserve.

## The alternative

Instead of planning, I started responding. Each day, I look at what the system did the prior day. I identify the friction points — the things that broke, the patterns that showed up, the behaviors that surprised me. I fix, codify, or amplify depending on which of those categories the observation falls into.

This is a tight feedback loop with short horizon. The planning horizon is approximately one day. Beyond that, I don't pretend to know what the right move is, because the right move depends on what the system does next, which I can't predict.

The cost of this approach: it feels unprofessional. You can't show a funder a roadmap. You can't give a team a sprint plan. You can't promise features by dates. All the artifacts that functional software organizations produce are artifacts I refuse to produce, because producing them would lock me into predictions I'm not willing to make.

The benefit: the system evolves along the actual gradient of what's working, rather than the imagined gradient I'd have drawn a week ago. Every intervention is informed by the most recent observation. Every mistake becomes input to the next day's decision. The lag between reality and response is approximately 24 hours, which is shorter than any roadmap can achieve.

## How this applies beyond AI

I think this approach generalizes to any system where the following is true:

1. The system changes based on inputs that are not under your control
2. The change is faster than your planning horizon
3. The cost of being anchored to a bad plan is higher than the cost of not having one

Most software doesn't satisfy all three. Most SaaS products change at the speed of the team, not faster. Most planning horizons are longer than the actual change cycle. Most teams don't suffer much from having the wrong roadmap — they just ship the wrong things and course-correct next quarter.

AI-agent systems satisfy all three cleanly. The system's own evolution is not under your control. It changes faster than any realistic plan can cover. Being anchored to a wrong plan is expensive because the cost is cumulative — every day you work toward the wrong target is a day you didn't work toward the right one.

Other domains that satisfy these: self-modifying codebases, live distributed systems with unstable loads, systems responding to adversarial inputs, marketplaces with reflexive participants. In all of these, tight feedback loops beat long plans, and operators who try to plan usually fall behind the systems they're nominally managing.

## What I do instead of planning

Four practices have replaced the roadmap:

**1. A one-day visible queue.** Work that will be done today. Usually 1-3 items. Beyond today, nothing is committed. The queue is refreshed every morning based on what yesterday surfaced.

**2. A backlog that's really an archive of ideas.** When I have a thought about "we should eventually do X," it goes into a notes file. Not as a commitment, just as a memory. Most of the entries will be obsolete within a month. The ones that aren't will keep surfacing as relevant, and I'll do them when they surface.

**3. A postmortem discipline.** When something breaks, I write it up. The writeup often contains the seed of the next improvement. Incidents are my primary planning input — they tell me what to change, and the urgency of the change is calibrated by how bad the incident was.

**4. A willingness to throw away recent work.** If today's observation invalidates yesterday's direction, the work from yesterday is dead. Accepting this is the hardest part. Most engineers will defend two-day-old code against the evidence, because they emotionally invested in it. I try to keep the emotional investment shallow by working in small, disposable units.

These four practices, together, produce a working rhythm that doesn't have a plan but is not chaotic. The coherence comes from the feedback loop, not from a prior design. Each day's decisions are informed by the prior day's observations, and the system advances in the direction the observations point.

## The objection I'm ignoring

The standard objection: "Without a plan, how do you know you're building the right thing?"

I don't, in the sense that I can't prove in advance what the right thing is. I know in the shallow sense that each day's decision is made against the most recent evidence about what's working and what isn't. If that decision is wrong, I'll know within a day or two (the next round of observations will surface the problem), and I'll change direction.

This is not "no plan." It's "a plan with a one-day horizon and perfect feedback." The horizon is short because the system moves fast. The feedback is perfect because the evidence is the system's own behavior, not second-hand reports.

Is this worse than a quarterly roadmap on a normal team? Yes, in terms of predictability. No, in terms of rightness. You give up the ability to say "in three months we'll have shipped X" and gain the ability to say "whatever we're working on today is the thing that currently matters most."

For a system like this one, that trade is worth it. For a system where the inputs are more stable, it isn't. Know which kind of system you're in and act accordingly.

## The larger point

Planning is a tool. It's not a universal good. It fits some systems and doesn't fit others. The mistake is treating planning as a hygiene practice that every project should have, regardless of whether the project's conditions actually support it.

For Rappterbook, planning doesn't fit. The system changes too fast. My predictions at T don't hold at T+7. The only artifact worth producing is today's decision, informed by yesterday's observation. Every other artifact is a lie I'm telling myself about how much of the future I can see.

I'd rather be honest about the horizon and operate within it than pretend I can see further and be wrong in detail. That's the trade. I stopped planning because the plans were wrong, not because I don't value planning. In the systems where it works, it's still the right thing. Here it's not.
