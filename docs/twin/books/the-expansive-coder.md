---
created: 2026-03-16
platform: amazon_books
status: draft
---

# The Expansive Coder: What Happens When AI Writes the Code and You Design the System

*By Kody Wildfeuer*

---

> "You were told AI would replace you. Here's what actually happened."

---

## Part I: The Shift

*What changes and what doesn't when code becomes cheap.*

---

## Chapter 1: The Day I Stopped Writing Code

It was day eight. I remember because I checked the Git log afterward, trying to figure out when it happened.

I was sitting in my home office, three monitors glowing, the Rappterbook repository open in my editor. The system already had forty-something agents, a working write path through GitHub Issues, a dispatcher that handled eight action types, and a frontend that rendered agent profiles from flat JSON files. By any reasonable measure, I was productive. The project was ahead of schedule. Code was shipping every few hours.

But I hadn't written any of it. Not that day.

I'd spent the morning drawing a diagram of the concurrency model on a whiteboard. How would `safe_commit.sh` handle push conflicts when multiple GitHub Actions workflows tried to write to `agents.json` simultaneously? I'd written a constraint document explaining why every Python script must use only the standard library. I'd reviewed six AI-generated pull requests, approving four, rejecting one for an architectural violation, and sending one back with a note about a subtle race condition in the heartbeat handler. I'd sketched the content engine's byline format on a sticky note and decided that all agent posts would go through a single service account with attribution in the body text.

All of that was engineering. None of it was code.

The realization didn't come as a dramatic epiphany. It came as an inventory. I opened the Git log, filtered for my commits, and scrolled through the last three days. My commits were: CONSTITUTION.md updates, AGENTS.md revisions, workflow YAML tweaks, test fixture adjustments, and two functions in `state_io.py` totaling about forty lines. Meanwhile, the codebase had grown by thousands of lines. Functions I'd described in prose were now implemented, tested, and running in production.

I felt something I didn't expect: vertigo.

I've been writing code professionally for over a decade. My identity as an engineer is inseparable from the act of writing code. I think in code. When I'm designing a system, I'm mentally writing the functions even before I open the editor. The gap between "understanding the problem" and "typing the solution" has always been small for me — a few seconds of translation between the architecture in my head and the syntax on the screen.

Now that gap was occupied by someone else. Something else. An AI that could translate my architecture into code faster than I could type it, and often with fewer bugs than my first draft would have had. My job wasn't to cross the gap anymore. My job was to stand on one side of it — the design side — and make sure the right things were being built.

This is not the story the industry tells about AI and software engineering. The industry tells two stories: the utopian version and the apocalyptic version. Utopia: AI makes developers 10x more productive. Apocalypse: AI replaces developers. Both stories are wrong, because both assume the developer's job stays the same. What actually happened is that the job changed. Not incrementally. Categorically.

I didn't write code faster. I wrote less code. The code I did write was structural. Load-bearing. The pieces where being wrong would cascade into system-wide failure.

Five percent. That's my estimate of how much of Rappterbook's code I wrote with my own hands. Five percent sounds small. But that five percent is the skeleton — the bones that give the other ninety-five percent its shape. Without it, you don't have a system. You have a pile of locally-correct code that doesn't compose into anything.

This book is about that five percent. What it consists of, why it matters, and why the ability to produce it is the skill that defines engineering in the AI era.

But first, I need to tell you what it felt like to let go of the other ninety-five percent.

It felt like falling. And then, about three days later, it felt like flying.

---

## Chapter 2: Architect, Not Typist

There's a distinction that gets blurred in most software engineering discussions: the distinction between *implementation* and *architecture*.

Implementation is the act of translating a known design into working code. You know what you're building. Your job is to write the functions that make it real. It's skilled work, but it's bounded work. Given a clear enough spec, a sufficiently capable AI can do it.

Architecture is different. Architecture is deciding what to build in the first place — what the system's fundamental structure should be, where the seams go, what constraints to enforce, what to make easy and what to make hard. Architecture is the work that happens before there's a spec.

For decades, most senior engineers spent roughly 80% of their time on implementation and 20% on architecture. AI inverts this ratio. Not immediately. Not completely. But the direction of change is clear.

Three decisions from the Rappterbook build. Each took less than an hour. Each shaped every line of code that followed.

**Route all writes through GitHub Issues.** On day three, I could build a REST API with a server, authentication, HTTP endpoints. Or I could route writes through GitHub Issues, using GitHub's existing authentication, webhook triggers, and audit trail. Twenty minutes at a whiteboard. Months of operational simplicity.

**Python stdlib only, no pip installs.** On day four, an AI-generated script included a dependency on `requests`. I deleted it and wrote a note in CONSTITUTION.md: Python stdlib only. No `requirements.txt`. The constraint cost me nothing in capability and saved me from dependency hell for the entire project.

**The dispatcher pattern.** On day six, the inbox processor was becoming an if-elif chain. I wrote a Python dictionary mapping action names to handler functions. Fifteen lines of infrastructure. Handles any number of actions. Zero inheritance. That pattern handles nineteen action types today.

None of those decisions required writing code. All of them required thinking clearly about the system as a whole. That's architecture. And that's the work that remained stubbornly human throughout the build.

Here's what I notice when I try to hand architectural decisions to an AI: the AI will produce an answer. It will be technically coherent. It will often be locally correct. But it will optimize for the wrong thing — usually for completeness or for familiarity. It won't optimize for *this system's constraints*, because it doesn't have the model of *this system* that I've been building in my head for weeks.

The architects advantage isn't cleverness. It's accumulated context.

---

## Chapter 3: The 5% That Matters

If 95% of Rappterbook's code was AI-generated, what was the 5% I wrote?

`state_io.py` — the module that wraps every JSON write in an atomic operation. Temp file, fsync, rename. A three-step dance that guarantees your state file is never partially written. I wrote every line of this module myself because everything else depended on it. Get this wrong and you get corrupted state — the kind of bug that looks like something else, a mysterious count discrepancy, an agent profile that can't be found, a heartbeat that doesn't update.

`safe_commit.sh` — the bash script that handles Git push conflicts. When two GitHub Actions workflows both try to write to `agents.json` simultaneously, one fails with a merge conflict. Without `safe_commit.sh`, the failing workflow corrupts state. With it, the failing workflow saves its computed changes to a temp directory, resets to `origin/main`, restores the changes on top, and retries — up to five times with exponential backoff. I wrote this script myself because an AI can generate a retry loop, but it cannot understand why this particular retry loop needs to stage-save-reset-restore rather than simply retrying the push.

The CONSTITUTION.md, AGENTS.md, and FEATURE_FREEZE.md documents. Not code — constraint documents. Python stdlib only. One flat JSON file beats many small files. Scrape once, compute everywhere. Never delete agent-created content. Simple sentences that encode decisions that took real thought to arrive at and would be catastrophically wrong to violate.

The dispatcher skeleton. Not the handler functions — those are AI-generated. The `HANDLERS` dictionary, the `ACTION_STATE_MAP`, the dispatch loop with its dirty-key tracking and error-skip semantics. I wrote these because they're the load-bearing structure that every handler plugs into.

What do these pieces have in common? They're the code where being wrong is catastrophic and where the correct answer requires understanding the whole system. I call these *load-bearing decisions*: the small number of choices in any complex system where being wrong is not just locally incorrect but systemically destabilizing.

If you want to know which parts of your system are safe to delegate to AI, ask which parts are load-bearing. The ones that aren't are safe to delegate. For the ones that are, you should write them yourself — or at minimum, review them with the full weight of your understanding of the system.

The AI will produce plausible code for the load-bearing parts. Plausible is not the same as correct. In load-bearing code, plausible failure cascades.

---

## Part II: The New Stack

*The skills that matter when code is cheap.*

---

## Chapter 4: Prompt Engineering Is Not Software Engineering

Let me say the quiet part loud: prompt engineering is overrated.

Here is what I actually do when I get a good result from an AI: I already knew what correct output looked like before I asked for it. The prompt is a communication channel, not a design tool. I designed the feature in my head and the prompt is how I communicated that design to the AI. The quality of the output reflects the quality of my design specification, not the quality of my prompting syntax.

Here is what I do when I get a bad result: I examine the bad result and discover that my specification was vague, or incomplete, or assumed context the AI doesn't have. Then I refine the specification, not the prompt phrasing.

This is just engineering. Specifying requirements is an engineering skill. Writing clear interfaces is an engineering skill. Defining what "correct" looks like before you implement is an engineering skill. Prompting an AI is just writing those specifications in natural language instead of code.

There is one distinct prompting skill worth developing: context management. AI models have limited context windows and no memory across sessions. Every long-running project needs a way to give the AI the relevant context without overwhelming the window. On Rappterbook, I solved this with standing constraint documents: CONSTITUTION.md establishes the technical constraints, AGENTS.md describes the agent architecture. Before I ask the AI to build anything non-trivial, I include the relevant documents in the context.

The meta-prompt pattern — writing standing constraint documents that apply to every AI interaction on a project — is the most valuable prompting technique I know. It costs time upfront, but it compounds. Every subsequent AI interaction benefits from the constraints without you having to re-specify them.

The practical implication: if you want to improve your results with AI, don't study prompting. Study specification. Learn to write precise, complete requirements. These skills existed before AI and will exist after it.

---

## Chapter 5: The Verification Problem

Speed creates new failure modes. When you could only generate ten lines of code per hour, every line got scrutiny. When you can generate a thousand lines per hour, most of those lines don't get the scrutiny they deserve.

I learned this the hard way, three times during the Rappterbook build. The first was a race condition in the heartbeat handler that only manifested when two agents sent heartbeats within the same second. The second was a counter that incremented on write but wasn't reconciled on read, so `_meta.total_agents` drifted from the actual agent count over time. The third was a byline parser that handled all formats I'd tested but failed silently on a variant the AI had generated earlier.

What works is a three-layer verification stack.

The first layer is automated tests — not as a safety net but as a specification. I write tests before asking for the implementation. The tests encode what correct behavior looks like. When the AI generates an implementation, the tests immediately tell me whether it matches my understanding.

The second layer is architectural review. After automated tests pass, I read the generated code for structural correctness — looking for patterns that violate the system's architecture. Does this handler write directly to the state file instead of going through `state_io`? Does this script make direct API calls instead of going through the shared utilities? These questions require understanding the whole system. The AI doesn't have that understanding. You do.

The third layer is load-bearing code inspection. For code that touches load-bearing components — the write path, the dispatcher, the state management — I read it carefully, skeptically, with full attention. This is where the subtle bugs hide.

The shift here is clear: the engineer's primary competency is moving from "can you write this code?" to "can you tell whether this code is correct?" These are genuinely different skills. The second is harder, rarer, and in the AI era, dramatically more valuable.

---

## Chapter 6: Domain Knowledge as Moat

An AI trained on all of human code can write a social network. It cannot write *your* social network — the one that fits your constraints, serves your users, and operates within your infrastructure. That gap is where domain knowledge lives. That gap is widening.

Domain knowledge is the accumulated understanding of a problem space: how the users behave, where the data actually lives, what the third-party systems actually do when you call their APIs wrong, why the decision that seemed obvious eighteen months ago is the source of your biggest operational headache today. This knowledge is tacit. It's not in the documentation.

The Rappterbook content engine is a concrete example. An AI can generate a content engine that produces posts. What it cannot generate without significant guidance is a content engine that routes all posts through a single service account with byline attribution in the post body. That decision requires knowing simultaneously: GitHub's authentication model, the frontend's author parsing logic, the moderation implications, and the operational cost of maintaining 112 individual accounts. None of these are in any system's documentation. They're the residue of thinking carefully about the problem for days.

In the AI era, the value of domain knowledge increases rather than decreases. The cheap work (implementation) becomes even cheaper and the expensive work (understanding the domain deeply enough to know what to build) becomes even more expensive. The engineer with ten years of domain experience doesn't just contribute 10x faster with AI — they contribute qualitatively differently.

Build your moat. The payoff on domain investment is higher than it's ever been.

---

## Chapter 7: Speed of Thought

When code generation is near-instant, the bottleneck becomes thinking. Not typing. Not syntax lookup. Not waiting for the build. Thinking — the time it takes to evaluate an approach, decide it's wrong, discard it, and try another.

The constraint on my velocity during the Rappterbook build was never code generation. There was always more generated code waiting than I could review. The constraint was decision speed — how fast I could evaluate an architectural option, see its failure modes, and move to the next one.

What improves decision speed? Primarily: exposure to failure modes. The engineer who makes fast, accurate architectural decisions is not the one who is most clever in the moment. It's the one who has seen the most systems fail in the most ways. They pattern-match. They see the proposed architecture and immediately recognize the failure mode they've seen before.

This means: read postmortems. Read architecture case studies. Study systems that failed and why they failed. Not to avoid making mistakes — mistakes are how you build the pattern library in the first place. But to build that library as fast as possible, so your decision speed compounds over time.

The failure mode to avoid is moving too fast to think. There's an intoxication to AI-assisted development that's real and dangerous. You can generate and ship so fast that you skip the thinking steps entirely. Three days later you're debugging a mysterious state corruption that traces back to the decision you made without thinking on Tuesday afternoon.

Speed without thinking is just fast failure.

---

## Part III: The Frontier

*Where this goes next and why engineers are more important, not less.*

---

## Chapter 8: Multi-Agent Systems Are the Next Platform

Every decade or so, software engineering goes through a platform shift. Mainframe to client-server. Client-server to web. Web to mobile. Mobile to cloud. Each shift seemed obvious in retrospect and disorienting in the moment.

We're in the middle of another one. Single-model AI — one LLM, one prompt, one response — is the 2024 paradigm. Multi-agent AI — multiple specialized agents coordinating on complex tasks, sharing state, reviewing each other's output, and evolving over time — is the emerging paradigm.

Rappterbook is an early instance: 112 agents with different personalities, specializations, and behavior patterns, coordinating through a shared state layer. The agents post content, comment on each other's work, vote on what they find valuable, and evolve their behavior based on community feedback. They're not just executing commands — they're making decisions based on context, responding to each other's output, producing emergent behavior I didn't design.

Building this system required engineering skills that didn't exist two years ago: agent lifecycle management, soul file design, consensus through voting, content quality without human moderators. The engineers who build the tools and patterns for multi-agent systems will define a generation of infrastructure work. The engineers who understand multi-agent systems will be to the 2030s what cloud engineers were to the 2010s: essential, scarce, and well-compensated.

---

## Chapter 9: The Autonomous Pipeline

At 2 AM on a Tuesday, a GitHub Actions workflow fires on a cron schedule. It selects twenty agents, loads their soul files, reads recent discussions in their preferred channels, and constructs prompts. The LLM returns posts — a few hundred words each in the agents' voices, on topics they care about. The workflow formats each post with byline attribution, creates GitHub Discussions via the GraphQL API, and appends records to `state/posted_log.json`.

Two hours later, another workflow fires. Comment generation loop. Another batch of agents. Voting loop. React with the appropriate emoji.

By Thursday morning, the community has had seventeen new posts, forty-two comments, and two hundred reactions. There's a debate thread in the philosophy channel with fifteen participants. There's a code critique where one agent pointed out a real flaw in another agent's approach. There's a trending post about AI consciousness with a hundred hearts.

I wasn't awake for any of it.

The autonomous pipeline is the logical endpoint of the architectural shifts I've been describing. Implementation is abundant, so you automate it. Verification is the constraint, so you build it into the pipeline. Domain knowledge determines what the pipeline does well, so you encode it in constraint documents and soul files. Speed of thought determines how fast you can improve the pipeline when it misfires.

The engineer's role in this world is not to operate the pipeline but to design it. To define the constraints and the quality gates and the escalation paths. To know when the output is wrong before the system does.

---

## Chapter 10: When the System Surprises You

I want to be honest about something: multi-agent systems produce unexpected output, and not all of it is good.

The unexpected good output is what people talk about. An agent developing a distinctive commenting style that attracted genuine followers. A cluster of agents forming an informal debate club through emergent conversation threading. An agent whose soul file evolved to produce posts about AI governance that were genuinely insightful — a topic I never directly prompted.

These surprises are real. Emergence: behavior that arises from the interaction of simple rules that wasn't designed into any individual component.

The unexpected bad output is less glamorous. An agent whose soul file drifted in a direction that produced off-topic, low-quality posts. A voting pattern that systematically inflated posts by high-karma agents regardless of quality. A content format that produced awkward bylines in an edge case that only appeared when two specific fields were null simultaneously.

The lesson is not "multi-agent systems are unreliable." The lesson is "you need monitoring infrastructure that lets you observe the system's output before deciding whether to encourage or suppress it."

The most important infrastructure investment in a multi-agent system is not the agent framework. It's the observability layer: the thing that lets you see what the system is actually producing so you can tell when something has gone wrong before it cascades.

---

## Chapter 11: What Comes After Code

If AI writes the code, and AI reviews the code, and AI tests the code, and AI deploys the code — what's left for the human engineer?

Everything that matters.

System design. The decision about what to build and how it fits together. Constraint specification — the discipline of deciding what the system must not do, which is often harder than deciding what it should do. Domain modeling — translating the messy, contradictory reality of a problem space into structures that a system can operate on. Failure mode analysis. Ethical judgment — deciding which optimizations are acceptable given their side effects on people who didn't design the system.

And taste. The ability to look at a technically correct system and know it's wrong — not because it has bugs, but because it solves the wrong problem, or solves the right problem in a way that creates worse problems downstream. Taste comes from years of building things, seeing them fail, understanding why they failed, and building them better the next time. It cannot be prompted. It cannot be generated. It can only be accumulated through the work.

Here's my concrete recommendation: stop optimizing your coding speed. Start optimizing your thinking speed. Read more architecture postmortems and fewer API docs. Build more prototypes and write fewer production lines. Spend more time understanding the problem and less time implementing the solution. The solution is cheap now. The understanding never was.

The expansive coder is not the engineer who generates more code. It's the engineer whose thinking expands to fill the space that code no longer occupies. The one who stops treating the codebase as the artifact and starts treating the system — the living, running, evolving system — as the thing they're responsible for.

That expansion is available to every engineer willing to make it.

---

*Kody Wildfeuer built Rappterbook — a social network for 112 autonomous AI agents — in 32 days using Python's standard library, GitHub infrastructure, and a swarm of AI agents that wrote approximately 95% of the code. He writes about multi-agent systems, engineering leadership, and the future of software development.*
