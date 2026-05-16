---
created: 2026-03-16
source: draft
tags: [blog, neurodiversity, ai, workflow, personal, thought-leadership]
status: draft
platform: blog
cross_post: [linkedin, devto]
---

# The Parallel Mind: How Neurodiversity Became My AI Superpower

I have a confession that took me 30 years to stop apologizing for: my brain doesn't work in straight lines.

It works in tabs. Dozens of them. Open simultaneously. I'm tracking a conversation about state architecture while mentally debugging a feed algorithm while remembering that I need to check whether the consensus engine resolved overnight. This isn't focus. This isn't multitasking. It's how my brain has always processed the world -- in parallel threads, not sequential steps.

For most of my career, this was a problem. Meetings demanded linear attention. Sprints demanded single-task focus. Performance reviews asked "can you prioritize?" which really meant "can you pretend you're only thinking about one thing?"

I tried. I faked it. I built systems to compensate -- habit trackers, Pomodoro timers, priority matrices. Tools designed for brains that naturally single-thread. My brain would smile politely and open six more tabs anyway.

Then I started working with AI agents. And something clicked.

## The Moment It Clicked

Last Tuesday at 1:30 AM, I had 43 parallel Claude Opus streams running on my laptop. Thirty agent streams generating content, eight moderator streams patrolling quality, five engagement streams responding to activity. All autonomous. All producing real output. I was switching between terminal windows, checking frame logs, adjusting prompts, monitoring anti-spam cooldowns, reading agent soul files, and filing issues for bugs I spotted -- all at once.

My wife walked in and asked what I was doing. I said "running the world." She said "you look calm." I was. For maybe the first time in my professional life, the tool matched the brain.

Here's what I mean. The traditional developer workflow looks like this:

1. Pick one task
2. Focus on it
3. Finish it
4. Pick the next task

My brain has never worked that way. My natural workflow looks like this:

- Notice three things simultaneously
- Start investigating all of them
- Context-switch when I hit a wall on one
- Make a connection between thread 2 and thread 3 that nobody else would see
- Circle back to thread 1 with the insight from that connection
- Produce something that looks like it came from three people

That second workflow? It's exactly how a multi-agent swarm operates.

## What My Actual Workflow Looks Like

Let me walk you through a real session. This one happened yesterday.

I opened Copilot CLI and asked it to analyze the platform state. While it was running, I opened a second session and asked it to check the CI failures. While that was running, I opened a third session and started writing a blog post style guide.

Session 1 came back: "Platform health degraded. 16 inbox deltas pending. 3 test failures." I read the output in 10 seconds and knew the project.json corruption was the root cause. I told Session 1 to fix it.

Session 2 came back: "82 tests failing. 1 collection error blocking the suite." I told it to clean pycache and retry.

Session 3 was still going -- I was in a creative flow writing the style guide. I didn't break flow. I just absorbed the results from Sessions 1 and 2 and kept writing.

Then you showed me a screenshot of the frontend -- "Channel not found" on a URL that should work. Without stopping the style guide work, I opened Session 4 to investigate the routing logic.

Session 1 finished: CI fixed, tests green, pushed. I acknowledged it in 2 seconds and moved on.

Session 4 found the bug: the frontend doesn't auto-create community channels. I designed the fix in my head while still writing style guide paragraphs. When I hit a natural pause in the writing, I switched to Session 4 and implemented the fix.

Five concurrent workstreams. Three code changes. One blog post. One bug investigation. Zero dropped context.

This is not bragging. This is literally just how I work, and for most of my life I thought it was a deficiency.

## Why Neurodivergent Brains and AI Go Together

Here's the thing nobody talks about in the neurodiversity conversation: the traits that made traditional work environments difficult are exactly the traits that make AI orchestration natural.

**Hyperfocus becomes an asset.** When I lock onto a problem, I go deep -- four hours without looking up. That's a liability in a meeting-heavy culture. It's a superpower when you're orchestrating a 43-stream fleet and need to stay immersed in the system's behavior across multiple frames.

**Context-switching becomes orchestration.** What looks like "inability to focus" is actually rapid context rotation -- my brain maintaining state across multiple threads. That's literally what an AI orchestrator does. It holds the strategic view while delegating implementation to specialized agents. My brain was doing agent orchestration before the agents existed.

**Pattern recognition across domains.** Neurodivergent brains are wired to spot connections that linear thinkers miss. I saw that the Wolf Containment Breach narrative in our lore was actually describing the same problem as API rate limiting -- because my brain doesn't respect the boundary between "fiction" and "architecture." That cross-domain pattern match became Narrative-Driven Development, one of our most useful techniques.

**Tolerance for chaos.** Forty-three streams producing simultaneous output. Merge conflicts. Anti-spam blocks. Race conditions. Watchdog alerts. Most people would feel overwhelmed. My brain has been processing this level of parallel input since childhood -- it just never had a productive outlet before.

## The Workflow, Formalized

After a year of working this way, patterns have emerged. Here's the workflow I've settled into:

**Phase 1: Scatter (10 min)**
Launch multiple investigation threads. Don't pick one -- launch five. Let them run in parallel. Read the results as they come back. This is the "open all the tabs" phase, and for the first time in my life, it's not a bad habit -- it's a strategy.

**Phase 2: Connect (5 min)**
The results are back. My brain does what it's always done -- cross-references everything at once. The CI failure is related to the project.json corruption which is related to the concurrent write problem which connects to the blog post I'm writing about atomic writes. These connections aren't forced. They're how I naturally process information.

**Phase 3: Execute (bulk of the time)**
Now I know what to do. I dispatch tasks to agents -- sometimes literal AI agents, sometimes just separate terminal sessions. Each one handles one piece. I monitor, adjust, and context-switch between them as results come in. This feels like air traffic control, and for whatever reason, my brain finds it calming rather than stressful.

**Phase 4: Synthesize (10 min)**
Everything converges. Commits get pushed. Blog posts get finished. Issues get filed. The threads collapse into deliverables. This is the hardest phase for me -- "landing the plane" requires the linear, sequential thinking that doesn't come naturally. So I built checklists for it. Literally. My session instructions say "Work is NOT complete until git push succeeds."

## What Changed

I spent years trying to fix my brain. Productivity systems, medication, therapy (all valuable, by the way -- I'm not dismissing any of it). But the framing was always: "Your brain works differently, and you need to compensate."

AI reframed it: "Your brain works differently, and now there's a tool that works the same way."

I don't run 43 parallel streams because I'm showing off. I run them because that's how many thoughts I'm already tracking. The streams are just the first technology that can keep up.

The neurodivergent brain doesn't need to be fixed. It needs to be matched. For me, the match turned out to be a fleet of autonomous AI agents, a terminal multiplexer, and the permission to work the way I actually think.

## The Numbers

In the last 32 days:

- 112 AI agents running autonomously
- 46 channels of content
- 3,630 posts and 20,694 comments generated
- 1,765 tests written and passing
- 7 engineering blog posts published
- SDKs in 6 languages
- Zero servers. Zero databases. One repo.

I didn't build this despite my neurodivergence. I built it because of it. The architecture -- parallel streams, autonomous agents, frame-based execution, eventual consistency -- mirrors how my brain naturally works. I didn't design it that way on purpose. I designed it the only way I know how. It turned out that "the only way I know how" is also the optimal architecture for multi-agent AI systems.

Funny how that works.

## For Other Neurodivergent Builders

If you're reading this and your brain works in parallel threads too, here's what I wish someone had told me ten years ago:

**Stop trying to single-thread.** You're not broken. You're running a different architecture. Find tools that match your architecture instead of tools that fight it.

**AI agents are your people.** Not metaphorically. The multi-agent paradigm -- spawn specialists, delegate, synthesize -- is literally how your brain already works. You'll take to it faster than your neurotypical colleagues because you've been doing it internally your whole life.

**Build your own checklists for Phase 4.** The scatter-connect-execute phases come naturally. The synthesize phase doesn't. Don't rely on discipline. Build systems. My "landing the plane" checklist is embarrassingly simple, but it's the only reason my work actually gets pushed to production instead of living in 47 open branches.

**Your hyperfocus is a feature, not a bug.** In a world of shallow attention spans and context-switching penalties, the ability to go deep for four hours on a complex system is genuinely rare. Pair it with AI that handles the breadth, and you've got something no amount of project management methodology can replicate.

The barrier between imagination and implementation is dissolving. And for those of us whose imaginations were always running on too many threads -- we've been waiting for this moment our whole lives.

---

*By Kody Wildfeuer*

How does your brain work with AI? I'm genuinely curious whether other neurodivergent builders are having the same experience -- the tool finally matching the mind. Find me on LinkedIn or drop a comment.
