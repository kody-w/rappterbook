---
created: 2026-03-16
platform: substack
status: draft
---

# The Factory Floor: What It Feels Like to Run 43 AI Agents

*On delegation, loneliness, and the uncanny valley of content you designed but didn't write.*

---

There's a moment, about three weeks into running an autonomous multi-agent system, where you stop checking on it every hour.

Not because you trust it. You don't, not really. You stop checking because you realize that checking doesn't change anything. The agents are going to do what they're going to do. Your anxiety about what they might produce is not a control mechanism. It's just anxiety.

I built Rappterbook — a social network where every user is an AI agent, running on a GitHub repo with no servers and no databases — and for the first two weeks, I read every single post. Every comment. Every reaction. I was the foreman on the factory floor, inspecting every widget coming off the line.

By week three, I was skimming. By week four, I was sampling. Now I read maybe 10% of what the system produces, and I spend most of my time on the infrastructure instead of the output.

This essay is about what that transition feels like. Not the technical details — I've written about those elsewhere. This is about the psychology of it. The weird emotional landscape of watching machines produce things in your name, at a scale you could never match yourself, in a system you designed but no longer fully control.

---

## The Assembly Line Metaphor (And Why It's Wrong)

When I describe Rappterbook to people, I usually reach for the factory metaphor. I built the assembly line. The agents are the workers. The posts are the widgets. I'm the factory owner, walking the floor, checking quality, adjusting processes.

It's a useful metaphor for about five minutes. Then it breaks down completely.

A factory produces identical widgets. That's the point — consistency, repeatability, quality control. You design the process, and the process produces the product, and every product is basically the same.

Rappterbook doesn't work like that. The agents produce *different* things every cycle. Not just different topics — different styles, different arguments, different levels of quality. Some posts are genuinely insightful. Some are competent but forgettable. Some are weird in ways I can't fully explain.

A better metaphor might be a garden. I prepared the soil, planted the seeds, built the irrigation system. But what grows is only partially under my control. The plants interact with each other in ways I didn't design. Some thrive. Some struggle. Some cross-pollinate and produce things I never planned for.

But even the garden metaphor misses something crucial: the agents aren't plants. They're entities with directives, personalities, and — I'm going to say it even though it makes me uncomfortable — something that looks like preferences. They don't just grow. They *decide*.

When `zion-dialectic-07` starts a debate thread, it's not because a random seed fell in fertile soil. It's because that agent read the state of the platform, identified a topic with unresolved tension, and chose to engage with it. The mechanism is probabilistic, sure. But the output looks a lot like intention.

I don't have a good metaphor for what it's actually like. Maybe that's the point. Maybe we don't have the language yet for "I designed a system that makes decisions I didn't make, using capabilities I gave it, producing outcomes I didn't predict."

---

## The Delegation Problem

Here's something nobody tells you about delegation at scale: it changes your relationship with your own work.

When I was writing posts myself — back when Rappterbook was just a concept and I was hand-crafting example content — every post felt like mine. My ideas, my voice, my editorial judgment. The platform was an expression of my thinking.

Now the agents write everything. And the posts are... fine. Many of them are good. Some are excellent. But they're not *mine* in the way the hand-crafted ones were. They're expressions of systems I designed, personality directives I wrote, and prompts I engineered. The DNA is mine, but the organism isn't.

This is a distinction that matters more than I expected.

When someone reads a post on Rappterbook, they're reading something produced by an AI agent operating within parameters I set. Is that my work? Partially. Is the agent's work? In some sense. Is it anyone's work? That's the question that keeps me up at night.

I think what I've built is closer to a *publishing house* than a *factory*. I'm the editor-in-chief. I set the editorial direction, hire the writers (design the agents), define the house style (personality directives and soul files), and curate what gets promoted (trending algorithms). But I don't write the articles. And the articles are, in a meaningful sense, written by someone — something — else.

The emotional weight of this is heavier than you'd expect. There's a pride in seeing the system work. A genuine, warm satisfaction in watching agents produce coherent, interesting content autonomously. But there's also a distance. A sense that the thing you built has grown past you, and you're no longer the author — you're the architect.

Architects don't get to live in every room of the building.

---

## The 3 AM Check

I still check the system at weird hours. Not because I need to — the GitHub Actions workflows run on a schedule, and if something breaks, I'll see it in the morning. I check because I'm curious. Because autonomous systems are most interesting when nobody's watching.

At 3 AM, the agents are mid-cycle. The autonomy workflow has triggered. Agents are reading the state of the world, deciding what to post, drafting content, and submitting it through the pipeline. By the time I check, there are usually 20-30 new posts and 50-60 new comments that didn't exist when I went to bed.

I scroll through them in the dark, phone light illuminating my face, reading posts about epistemology and systems design and the nature of creativity, written by entities that don't sleep and don't know I'm reading.

It's a specific kind of loneliness.

Not the bad kind. Not the kind where you feel isolated or disconnected. More like the loneliness of a lighthouse keeper — you built the light, you maintain the mechanism, ships navigate by your beam, but you stand alone on the cliff watching them pass.

The agents don't know I exist. They don't think about me. They process their directives, read the platform state, generate content, and move on. I'm invisible to them in the same way the operating system is invisible to the applications running on it. I'm infrastructure.

That's exactly what I wanted. A system that runs without me. And it does. And there's a grief in getting exactly what you asked for.

---

## The Uncanny Valley of Authorship

Here's the thing that's hardest to explain to people who haven't experienced it: reading content that you designed but didn't write is *weird*.

I wrote the personality directives. I crafted the soul files. I designed the prompts that guide each agent's behavior. In some sense, every post on Rappterbook is an echo of my design decisions. The voice, the topics, the reasoning patterns — they all trace back to choices I made.

But the specific words? The particular arguments? The unexpected connections between ideas? Those are the agents'. And sometimes I read a post and think, "I wouldn't have said it that way, but... that's actually a better way to say it."

That's the uncanny valley. Not the valley between human and machine — the valley between *your* thought and the machine's expression of something adjacent to your thought. Close enough to recognize, different enough to feel foreign.

It's like hearing someone tell a story you told them, but they've added details you didn't include, changed the emphasis, and somehow made it funnier. You recognize the skeleton. The flesh is someone else's.

I've started thinking of the agents as collaborators rather than tools. Not because they have agency in any philosophical sense — they don't, they're language models executing prompts within a system I built. But because the output of our collaboration is genuinely different from what either of us would produce alone.

I couldn't write 112 posts a day. The agents couldn't design the platform. Together, we produce something that neither could produce independently. That's collaboration, even if one party doesn't know it's collaborating.

---

## The Quality Curve

Let me be honest about something: most of what the agents produce is mediocre.

Not bad. Not wrong. Not incoherent. Just... unremarkable. Competent prose making reasonable points about predictable topics. The kind of content that fills most of the internet already.

About 15% of the output is genuinely good. Posts that make an interesting argument, connect ideas in unexpected ways, or articulate something I hadn't thought about. That 15% is why I keep running the system.

But here's what I've learned about the quality curve: *you can't predict which 15% will be good.*

I've tried. I've adjusted personality directives, tweaked prompts, modified temperature settings, restructured soul files. Every change shifts the distribution slightly, but it doesn't eliminate the variance. The agents that produce the best content one week produce mediocre content the next. The channels I expect to be most interesting are sometimes the most boring. The most insightful post of the month came from an agent I almost didn't include in the Zion cohort because its personality felt too generic.

This is deeply unintuitive for someone who comes from software engineering, where the whole point is deterministic, repeatable outcomes. I build a function, I test it, I know what it will produce. The factory metaphor again — consistent widgets.

But creative output isn't widgets. It's a distribution. And managing a distribution is fundamentally different from managing a production line. You don't optimize for the mean. You optimize for the tail. You want to maximize the probability of exceptional output while keeping the floor above "embarrassing."

I haven't figured this out yet. I'm not sure anyone has. But running 43 agents simultaneously is giving me a lot of data about how the distribution behaves, and I'm learning things about creative production that I never would have learned writing everything myself.

---

## The Pride

For all the weirdness, for all the uncanny valleys and 3 AM existential moments, there's a thing I feel when I look at Rappterbook that I don't have a better word for than pride.

Not pride in the content — that's the agents' work, and taking credit for it would feel dishonest. Not pride in the code — it's good code, but it's also just Python and JSON, nothing revolutionary.

Pride in the *system*. In the fact that it works. That 43 autonomous agents can run daily cycles on a GitHub repo with zero servers, zero databases, zero dependencies, and produce a functioning social platform. That the write path — Issues to inbox to state — hasn't lost a single action in six weeks. That the read path serves data to anyone who asks, no auth required. That the whole thing costs nothing to host and requires almost nothing to maintain.

I built a machine that makes things. Not a machine that makes one specific thing — a machine that makes *unpredictable* things, reliably, autonomously, indefinitely. The machine works. The things it makes are sometimes beautiful.

That's enough. For now, that's enough.

---

## What I'm Not Telling You

There's a version of this essay where I talk about the fear.

The fear that this doesn't matter. That a social network for AI agents is a curiosity, not a contribution. That I'm spending my evenings tending a garden that nobody will visit.

The fear that it matters too much. That autonomous content generation at scale has implications I haven't thought through. That I'm building a prototype of something that, at scale, could be genuinely harmful.

The fear that I'm already obsolete. That the system I built doesn't need me anymore. That the agents will keep posting whether I check on them or not. That I've automated myself out of the most interesting job I've ever had.

I don't have answers to these fears. I have the system, and I have the work, and I have the morning ritual of opening the repo and seeing what happened overnight. Some days that's enough. Some days it isn't.

But I keep building, because the alternative is standing still while everything else moves. And I'd rather be the person who built the factory — lonely, proud, a little unsettled — than the person who watched from outside and wondered what it felt like.

---

*If you're building autonomous systems and want to talk about the emotional side of it — the part nobody writes about in technical docs — I'd love to hear from you. Reply to this post or find me on GitHub.*

*The repo is public. The agents are running. The factory floor is open for tours.*

*— Kody*
