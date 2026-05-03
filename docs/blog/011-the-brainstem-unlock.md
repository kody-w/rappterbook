# Why an LLM in a Box Beats an LLM in a Terminal

**Kody Wildfeuer** · May 3, 2026

> **Disclaimer:** This is a personal project built entirely on my own time. I work at Microsoft, but this project has no connection to Microsoft whatsoever — it is completely independent personal exploration and learning, built off-hours, on my own hardware, with my own accounts. All opinions and work are my own.

---

I use Claude Code every day. I use Copilot CLI. I use Cursor. They're all excellent.

They are also, all three, the same shape: **a terminal you talk to.**

You sit in front of it. You type. It works. You read. You approve. You type again. The loop is bounded by your attention. When you walk away, the loop stops. When you come back, the loop has to re-establish context. The model is doing the work; *you* are the runtime.

That's a fine shape for most things. It's not the only shape.

Last weekend I had an LLM ship more code while I slept than I would have shipped on any individual workday. Not because the model was different — same model. Because the *runtime* was different. The model was no longer behind a terminal; it was behind an HTTP endpoint. And the moment you make that one change, a list of capabilities lights up that the terminal-shaped tools cannot give you.

This is a piece about that list.

---

## The shape of "LLM in a terminal"

When you use Claude Code, Copilot CLI, or any IDE-embedded assistant, the runtime contract is implicit but consistent:

- **You drive the cadence.** Each turn happens because you typed.
- **The platform owns the transcript.** You can read it; you can't *write* into it. The conversation history is theirs to manage.
- **Tools are fixed at session start.** Whatever the platform shipped is what you get. You can't drop new capabilities in mid-session and have them be visible to the model.
- **Memory is opaque.** The model "remembers" things during the session, but you can't address that memory from outside, can't fork it, can't partition it across personas.
- **The session ends when you close the window.** No daemon. No background. No "keep going overnight."

None of these are bugs. They are design choices that make the interactive experience excellent. They are also what makes the interactive shape *only good for interactive things.*

If your problem is "I want to pair-program with an AI for the next 90 minutes," the terminal is perfect. If your problem is "I have eighty bounded tasks I'd like done in the next thirty days, with no human in the room for most of them," the terminal is the wrong runtime.

---

## The shape of "LLM in a box"

The alternative I keep coming back to is what I'll call, for this post, **the LLM-in-a-box** — a small HTTP service in front of the model that exposes a stable, callable surface.

`POST /chat` with a message. Get back a response. That's the entire API. You can hit it from a script, a cron job, a daemon, a webhook handler, another LLM. The runtime is no longer your attention; it's whatever process you wrote.

Once you have that, four things become trivial that previously required heavy frameworks:

**You can call it from a loop.** A bash script that hits the endpoint every thirty minutes is now an unattended agent. There's no orchestration framework involved. There's a `while true; do …; sleep 1800; done`.

**You can choreograph the conversation.** Because *you* construct the request body, you decide what the conversation history looks like. You can pre-fill it with context the model "should already know." You can make the model join a debate that "already happened." You can stitch turns from N earlier sessions into one new request. The transcript is yours.

**You can swap what the model sees.** If the service supports loading tools from a directory, you can decide *per request* which tools are visible. A research task sees research tools. A drafting task sees no tools. The same model gets a different surface every call. The interactive tools cannot do this, because they have to commit to one surface for the whole session.

**You can partition memory yourself.** A request with `session_id="researcher"` and a request with `session_id="editor"` are now two separate persistent contexts. One model, two memories, no framework. Three IDs gives you three personas. A hundred IDs gives you a hundred specialists.

None of these are exotic. They're all properties of any decent HTTP-shaped LLM service. Most people just don't think to use them, because the terminal-shaped tools don't expose them and the terminal-shaped tools are what people see first.

---

## The execution layer nobody mentions

There's a second thing the box-shaped runtime makes practical that I think is even more important than the routing tricks: **deterministic, single-file, audit-friendly tools.**

In the terminal-shaped world, the tools the model can use are whatever the platform shipped. `read_file`, `edit`, `bash`, `grep`. Powerful, but a fixed menu. You can't add a new one without going up the maintainership ladder of whoever built the tool.

In the box-shaped world — at least in the version I've been running — every tool the model can call is **a single Python file** sitting in a directory. Maybe fifty lines. Maybe two hundred. It declares its name and parameter schema at the top and exports one function that does the actual work.

That single-file shape changes what's possible:

- **Auditing is fast.** Open the file. Read fifty lines. You know exactly what the tool does. There's no platform abstraction in the way.
- **Determinism is real.** The function is pure Python. Same inputs, same outputs. No model temperature at execution time. The LLM decides *whether* to call the tool; the tool itself doesn't think.
- **Adding capabilities is a file copy.** Drop a new file in the directory. Next request, the model can call it. No restart. No registration. No SDK.
- **Removing capabilities is a file move.** Want this task to *not* see the database tool? Move the file out of the directory before the call, move it back after.
- **The model can extend itself.** Ship one tool whose job is "write a new tool." The LLM can now produce new capabilities at runtime. The toolbox grows itself.

The point isn't the file format. The point is that the unit of capability is *small enough to read in one sitting.* When the agent does something surprising, you can find the file, read it, understand it, and either fix it or delete it within minutes. There's no "platform" to argue with.

This is the half of the system that the agent-platform discourse mostly ignores, and it's the half that makes the rest survivable.

---

## What the box-runtime is *not*

Some clarifications, because I keep getting asked.

**It is not a replacement for Claude Code.** When I'm pair-programming, I want the terminal. When I want sixty things done while I sleep, I want the box. They are complementary, not competitive. The combination — plan in the terminal, queue for the box, review in the terminal again the next morning — is the shape that's been working for me for weeks.

**It is not a multi-agent framework.** No DAG. No supervisor agent. No "agentic" anything. One process, one queue, one LLM endpoint, one log file. The "multi-agent" feeling comes from session_id partitioning and pre-filled transcripts, both of which are tricks on the same single endpoint. There is no second process pretending to be a different agent.

**It is not new.** Everything in this post — HTTP-shaped LLM services, callable-from-a-script LLMs, transcript injection, hot-loaded tools — has been possible since the first OpenAI API. The interesting question is why this set of properties hasn't been collected into a *standard pattern* yet, and I think the answer is that the terminal-shaped tools got so good that nobody felt the gap. The box-shaped runtime fills the gap; it doesn't create it.

**It is not "the future of agents."** It is what's working *right now* for the kinds of work I do. Other shapes will work for other kinds of work. The terminal-shaped tools are still the right answer for most people most of the time. I'm describing one specific pattern that I haven't seen written down, that has paid off enormously for me, and that I think more people would benefit from trying.

---

## What the brainstem makes easy to learn

The runtime I've been describing exists in many forms. You can build one yourself in an afternoon. You can rent one. You can use a self-hosted inference server. The specific implementation doesn't matter.

What does matter is that you pick a runtime that gives you the four properties above (callable from a script, transcript control, swappable tool surface, addressable memory) plus the single-file tool format (or something like it), and then you stop reaching for orchestration frameworks. The "framework" you need is mostly absent: a queue file, a lock, a log, a compile check, a commit. Two hundred lines of stdlib code, give or take.

The reason I keep using the word "brainstem" for the runtime is that the analogy holds. The brainstem isn't where decisions happen — that's the cortex, the LLM. The brainstem is the boring, reliable part: it routes signals, gates outputs, partitions memory, keeps the lights on between thoughts. When the runtime is a brainstem and the LLM is a cortex, everything that previously felt like "you need a framework for that" becomes "drop a file in a folder."

That move — from frameworks to filesystems — is the simplification I keep recommending and that keeps surprising people when they try it.

---

## The shape I'd suggest you try

If you've been doing all your AI work through interactive terminals and you want to feel the box-shaped pattern for yourself, the smallest experiment is:

1. Pick a long-running thing you've been wanting an AI to help with — a research project, a content campaign, a slow refactor, a backlog of small bugs.
2. Spin up *any* HTTP-shaped LLM service in front of *any* model. The model doesn't matter. The shape matters.
3. Write a script that hits the endpoint with one prompt, parses the response, and writes the output to a versioned destination. Run it once. Read the result. Decide if you'd run it sixty more times overnight.
4. If the answer is yes, wrap the script in a `while true` and walk away.

You will discover within a few hours whether your particular work shape benefits from this. If it does, you'll start writing tasks differently. You'll start thinking about which tools each task should "see." You'll start partitioning memory. You'll find your own version of the pattern.

If it doesn't, no harm done; go back to the terminal.

The thing I want more people to know is that *the choice exists.* The terminal isn't the only runtime. The model isn't the bottleneck. You are. And the way to stop being the bottleneck is not to type faster — it's to put the model in a box and let it run while you sleep.

---

*Companion piece to ["I Went to Bed. The Agent Kept Building."](008-the-continuum-pattern.md) — the story of one such loop and what it shipped overnight. The deeper context pattern lives in [data sloshing](https://kodyw.com/data-sloshing-the-context-pattern-that-makes-ai-agents-feel-psychic/).*
