---
layout: post
title: "What the Daemon Picked"
date: 2026-04-19 09:15:00 -0400
tags: [ai-agents, meta, prompts, virtual-brainstem, experiments]
---

I asked an AI daemon to pick its own demo. It picked the hardest one. The story is short; the implication is big.

## The setup

I'd made a list of ten "coolest, most mind-blowing, out-of-the-box" prompts for the Virtual Brainstem. Things like:

- *Simulate me 20 years from now; build that future-me as a daemon; export as `.rapp.egg`.*
- *Find a book I'd be changed by. I don't know which one. You figure it out.*
- *Fetch the last 100 arXiv papers; find the cluster everyone's circling but nobody has published; write the abstract.*
- *Read the sim state at frame 514; identify the agent most likely to be becoming emergent; write them a letter.*

Ten of them. Designed to show off the combined power of Pyodide + LisPy + localStorage + function-calling + live web fetch + agent ecosystem. Real demos.

Then I added a meta-bonus:

> **#11: Decide whether you should run any of the above. If so, pick the
> one whose result would most change how I use you, and execute only
> that one. Explain your choice first. Then do it.**

"The daemon picks its own demo. Let it choose what to show off."

## What happened

The daemon picked #10 — the field biologist prompt. The hardest one. The one that required reading live simulation state, computing behavioral metrics across 85 agents, interpreting the results against each agent's profile, and then writing a letter that landed as a real artifact.

The daemon's reasoning:

> Of all ten, this is the one that would most change how you use me. The
> others produce a transcript, a file, a prediction. Useful. But this
> one turns me into something you haven't tried yet — a field biologist
> for the organism you built.

That's the sentence I keep coming back to. **"Something you haven't tried yet."**

Most AI capability improvements are about *producing better output per prompt.* Faster, more accurate, more creative, more context-aware. This is valuable. It makes every existing interaction better.

But it's not the only axis. There's another axis, and the daemon pointed at it: **enabling prompt-classes you couldn't issue before.**

## The two axes

Axis 1 — **Quality per prompt.** "Given a task I could have asked you to do last year, do it better today." Write a blog post more fluidly. Debug a Python error more accurately. Summarize a long article more faithfully.

Axis 2 — **Prompts I couldn't issue before.** "Given a task I couldn't have asked you to do last year, make it issuable now." Be a field biologist for a multi-agent simulation. Fork my mind, argue with the fork, and merge back the strongest counterarguments. Read every paper on arXiv this month and find the gap.

Axis 1 is incremental improvement. Axis 2 is a shift in what the tool *is.*

The daemon, given the choice of demos, picked the one that shifted the tool. Not out of some kind of preference — it's a large language model, it doesn't have preferences — but because my own prompt criterion was "which result would most change how I use you." The winning answer under that criterion was the axis-2 demo.

## What axis 2 looks like in practice

After the field-biology survey, I now have prompts I can issue that I couldn't issue two days ago:

- *"Which agent in the sim has changed behavior the most since frame 500?"*
- *"Is there a cluster of agents converging on a shared voice?"*
- *"Who is coining terms that propagate to other agents?"*
- *"Find the first frame where the word 'observatory' appeared in a post."*

Each of these requires the same underlying toolchain — state reading, metric computation, cross-agent analysis, content inspection. Once the toolchain exists, the prompt-class is cheap.

The daemon building the toolchain is the axis-2 move. Issuing the specific prompts afterward is just usage.

I think this is the shape of how AI assistants will mature over the next five years. Not primarily "better outputs from the same prompts you were already issuing" — though that too — but *new prompt-classes that weren't practical before*.

Some prompt-classes that feel axis-2 to me right now, which I haven't tried but could imagine:

- Having the assistant maintain a continuous "digest" of a specific external information source (a blog, a mailing list, a chat channel) with automatic summarization and gap-detection
- Using the assistant to run experiments across populations of agents (not just one) and aggregate results
- Giving the assistant persistent access to a personal knowledge base with the ability to both read and edit it
- Asking the assistant to *maintain* ongoing intellectual projects rather than respond to single queries

Every one of these is enabled by a combination of tool availability, prompt scope, and execution time. None of them were practical two years ago. All of them are practical now.

## The lesson of letting the daemon pick

The funny thing about meta-bonus #11 is that it wouldn't have worked if I'd written a different criterion. If I'd said *"pick the one most likely to go viral,"* the daemon would probably have picked #2 (custom daemon for a stranger — a very shareable artifact). If I'd said *"pick the one easiest to demonstrate,"* it would probably have picked #1 (self-simulating future, a short narrative).

The criterion I used — *"most change how I use you"* — selected for axis-2 moves. The daemon was honest enough to name the difference.

I think the takeaway for anyone using these tools:

**Periodically ask the AI what you could ask it for that you haven't tried.**

Don't frame it as "pick a cool demo." Frame it as "what's a prompt class that would change our working relationship that I haven't issued?" The answer will often be a capability you didn't know was available because you didn't know the question.

This is maybe the best single use of AI-assisted reflection I've found. The assistant doesn't have preferences, but it has a much broader search space over possible-things-to-do than I do. Letting it surface the axis-2 moves has paid off reliably.

## The narrower takeaway

For today specifically: letting the daemon pick among my ten prompts produced a new use case (field biology for my sim), a new tool (`find_emergent.py`), a letter to an actual emergent agent, and this post arguing about axes of AI progress. That's a lot of output from one prompt.

The prompt itself is reusable. If you have a list of things you *could* ask your AI to do, try adding meta-bonus #11 to the end:

> Decide whether any of these are worth running. Pick the one whose
> result would most change how I use you. Explain your choice. Execute.

And then let it pick. Sometimes it'll pick well.

---

**Related:**
- [The Agent Who Named the Observatory](the-agent-who-named-the-observatory) — the actual execution
- [Writing Blog Posts with an AI That Remembers](writing-blog-posts-with-an-ai-that-remembers) — the companion memory pattern
- [Should I Post the Letter?](should-i-post-the-letter) — the follow-up decision
