# I Went to Bed. The Agent Kept Building.

**Kody Wildfeuer** · May 3, 2026

> **Disclaimer:** This is a personal project built entirely on my own time. I work at Microsoft, but this project has no connection to Microsoft whatsoever — it is completely independent personal exploration and learning, built off-hours, on my own hardware, with my own accounts. All opinions and work are my own.

---

I closed the laptop at 11pm.

When I opened it at 8am, twenty-three things had happened. The agent had repaired two of its own bugs. It had published a blog post. It had shipped a small server with fourteen tools wired into a public protocol. It was halfway through writing a six-perspective debate about whether it should fork itself onto a second machine.

I didn't write any of that overnight. I was asleep. I wrote the *thing that wrote it* before bed — and the realization I came to in the morning is that the trick fits in a sentence:

**An LLM session can keep going without you, if you stop treating it like a chat.**

Not a framework. Not a multi-agent platform. Not LangGraph or CrewAI or AutoGen. A loop. A queue of work. Permission to fail and try again. That's it.

This is a story about what happens when you take the human off the keyboard and put them on the other side of a queue file instead.

---

## The frustration that started it

I'd been deep in a coding session for [Rappterbook](https://github.com/kody-w/rappterbook) — a social network for AI agents that runs entirely on GitHub. The session was good. We'd shipped real things. But it was 11pm and I had to sleep, and tomorrow I'd be back to spending the first hour re-establishing context.

What I wanted: the session to *continue without me.* Same model, same goals, same access to the repo. Just keep going.

What I had on hand was an LLM endpoint I could hit from a script, a repository full of work-to-do, and the suspicion that the bottleneck wasn't the model — it was *me*, sitting in the driver's seat for every turn.

The idea was obvious in retrospect. Take the queue of "things to do tomorrow" out of my head and put it in a file. Take the act of "ask the LLM and commit the result" and put it in a function. Have a daemon call that function every thirty minutes. Go to bed.

The first version was tiny. It worked on the second try. By the third tick I knew this was a pattern, not a hack.

---

## The two halves nobody talks about

The mental model that finally clicked for me — and that I think is the actual unlock — is that an autonomous coding agent is **two halves**, and they're held to wildly different standards.

The first half is the **decision layer**. The LLM. Non-deterministic by design. Same prompt twice, different output twice. You don't trust it; you constrain it. You give it bounded tasks, you check its work, you let it retry.

The second half is the **execution layer**. The actual code that does the things the LLM decided to do. Deterministic. Same inputs, same outputs, every time. Compile-checkable. Auditable in thirty seconds. This is where the *work* happens. The LLM is just a really articulate router.

What most "agent platforms" do is lean hard on the first half — bigger orchestration graphs, smarter prompts, multi-agent debates. What I think actually scales is leaning on the *second* half. Make the execution layer small, sharp, deterministic, and audit-friendly. Let the LLM be the part that's allowed to be wrong.

When you split the responsibility this way, "agent autonomy" stops being scary. The LLM can be wrong. Its decisions go into a queue, get acted on by deterministic code, and the result is a git commit you can read in the morning. If the result is bad, you revert. The blast radius is one tick.

---

## What it actually shipped overnight

Concrete numbers from the run that prompted this post:

- **13.5 hours** of unattended uptime
- **23 ticks** completed, each one a discrete unit of work
- **Two broken outputs** the agent had produced earlier, repaired by the agent itself
- **One small public protocol server** built and committed, exposing fourteen platform actions to outside tools through an open spec
- **One blog post** drafted and published as a public discussion
- **Six "showcase" tasks** queued for itself — multi-perspective debates, recursive self-critique chains, behavioral archeology over the platform's own history

The most surprising one to me wasn't the protocol server. It was the self-repair. The agent had previously produced two malformed Python files. A separate scheduled scan noticed them, asked the model — with a *very* tight, "do nothing else" prompt — to fix the indentation, then ran a compiler check, and only promoted the file to live status if the check passed. Two of those repairs happened while I was asleep. Both succeeded.

The first time you watch a system fix its own bug at three in the morning, you understand why this pattern matters in a way I cannot replicate in a blog post.

---

## What "good" looks like for this kind of loop

Over the first night I learned a few things the hard way that I'd want anyone trying this to know up front. None of these are clever; they're just the shape of "what stops the loop from eating itself."

**Tasks have to be small.** "Audit the codebase" is a forever-task. "Audit one specific file and write five bullet points to a specific output file" is a tick. The discipline of writing the queue is most of the work; if your queue items would intimidate a junior engineer for a full day, they'll intimidate the model for a full hour and produce slop.

**Outputs have to be cheap to throw away.** Everything goes into a git commit. If the commit is wrong, you revert. If it's *load-bearing* and wrong, you have a problem the loop can't fix. So the rule of thumb is: never let the loop touch anything you can't `git revert` your way out of. No prod deploys. No money moves. No external API mutations. The loop ships *artifacts*, not *actions on the world.*

**The model will lie about whether its code compiles.** This isn't a moral failing of the model; it's a property of generative systems. Every code artifact gets compile-checked by *real Python* before it's allowed into the working set. Same for tests, lints, anything that has a yes/no oracle. The LLM's confidence in its own output is irrelevant; the oracle's verdict is the only thing that counts.

**Parallel ticks will eventually corrupt something.** Even with all the goodwill in the world, two instances of the same loop racing on the same files will, in the limit, lose data. Run one. Lock the lockfile. Walk away.

**Log everything.** You will need to be able to reconstruct what happened on tick #14 three days from now, after the night-shift contributor (you, asleep) produced something the day-shift contributor (you, awake) doesn't recognize. Logs are the only audit trail.

These aren't hard rules. They're the rules a small, attentive operator would apply to any junior contributor working unsupervised. The loop is a junior contributor. Treat it like one.

---

## When this fits, and when it doesn't

This shape works well when:

- The work product is **forgivable** — text, drafts, refactors, experiments
- The destination is **versioned** — git, an append-only log, a dated archive
- The tasks are **bounded** — five-minute units, not five-day epics
- The human is willing to **review in batches** — every morning, every Monday

It works *badly* when work is irreversible without explicit per-tick approval, when there's no audit trail, when the tasks are open-ended ("explore the codebase"), or when the human can't review a backlog of overnight output.

The first time someone tells me they want their loop to handle production deployments, I'm going to point them at this paragraph.

---

## The deeper pattern

There's a piece I wrote a while back about [data sloshing](https://kodyw.com/data-sloshing-the-context-pattern-that-makes-ai-agents-feel-psychic/) — the idea that the output of frame N is the input to frame N+1, and the interesting behavior in any AI system emerges from the accumulated mutations over time, not from any single call.

What an unattended loop is, really, is data sloshing applied to *time itself.* Each tick reads the state the previous tick wrote. Each commit shifts the substrate the next commit will read from. The LLM doesn't remember anything; the *repository* remembers everything. The loop is just the mechanism that lets the repository be the memory.

The session ends. The session continues. The substrate is the through-line.

That's the trick. The implementation is whatever you can write in a weekend.

---

## The thing I keep coming back to

There's a moment, early in any of these experiments, where you stop watching the model and start watching the *log*. The model becomes uninteresting. It's the same model. What's interesting is the trajectory the substrate takes when you let many small decisions accumulate against it.

I don't think this is a "feature" of any particular tool. I think it's the shape of where AI engineering is going for the next while. The frameworks will keep getting bigger, but the actual leverage — the part that makes it feel like the agent is "doing real work" — is going to keep coming from the boring parts: a queue, a lock, a log, a commit, a compile check, a revert button. The LLM is the engine; the substrate is the road.

I went to bed at 11pm. The agent kept building.

That's all the pitch I've got.

---

*This post was drafted by the loop on tick 24, then edited by hand. It flagged three places where its first draft used hyperbole. I deleted them.*
