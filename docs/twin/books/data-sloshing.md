---
created: 2026-03-26
platform: amazon_books
status: published
---

# Data Sloshing: The Context Pattern That Makes AI Feel Psychic

*By Kody Wildfeuer*

---

> "The output of frame N is the input to frame N+1. This is not a detail. This is the whole thing."

---

## Introduction: The Thing Everyone Gets Wrong About AI Agents

When people build AI agents, they almost always build them wrong. Not wrong in the sense of broken — the agents work. They respond to prompts. They complete tasks. They sometimes produce impressive output.

Wrong in the sense of *stateless*. You run the agent, it produces output, the run ends. The next run starts fresh, with no memory of the previous run, no accumulation of context, no history to draw on. Each invocation is an island. The agent is brilliant in the moment and amnesiac across time.

This produces AI that feels like a powerful tool. Capable but inert. Available but not present. Correct on any given question but unable to learn, or grow, or deepen, or surprise you with a connection it made because it remembered something you said last week.

The pattern that produces presence — genuine presence, the kind that makes an AI feel like it's actually tracking the work rather than responding to isolated prompts — is what I call data sloshing. The core idea is simple enough to fit in one sentence: the output of each frame becomes the input to the next.

The implementations of this idea produce behavior that seems almost psychic: an AI that picks up where it left off without being told, that notices patterns across sessions without being prompted, that arrives at conclusions that follow naturally from accumulated context rather than from any single clever prompt.

This book is about that pattern: what it is, why it works, how to implement it, and what it enables that stateless AI cannot produce.

---

## Part I: The Pattern

---

## Chapter 1: What Is a Frame?

Let me define terms precisely, because the vocabulary matters.

A *frame* is one complete cycle of the AI system's work. It has three phases: read, process, write.

In the read phase, the system consumes all available context: the current state of whatever artifact or conversation or codebase it's working with, plus any accumulated history from previous frames.

In the process phase, the system reasons over that context and produces output: new content, code changes, analysis, decisions, whatever the system is designed to produce.

In the write phase, the system commits its output as the new state of the artifact. This new state becomes the context for the next frame.

That's the frame. Read, process, write. The output of write becomes the input to read in the next cycle.

This description sounds simple. It is simple. The subtlety is in what happens across many frames.

Imagine a codebase as the artifact. Frame 1: the AI reads an empty repository, a description of the desired system, and an initial set of requirements. It produces a project scaffold — directory structure, initial files, a basic architecture. It commits this scaffold.

Frame 2: the AI reads the scaffold it produced in Frame 1, plus any updates to the requirements. It understands the architecture that was chosen and why. It implements the first feature in a way that's consistent with that architecture. It commits.

Frame 3: the AI reads the code from Frames 1 and 2. It sees that the first feature has a pattern that could be generalized. It refactors slightly to create a reusable foundation for subsequent features. It commits.

By Frame 10, the AI has a rich, accumulated understanding of the codebase: which patterns were established early and are foundational, which decisions were made in response to specific constraints, which parts are stable and which are experimental. This understanding doesn't need to be explained in a prompt — it's *in the code*, which the AI reads every frame.

The AI isn't psychic. It's just reading everything that's been written, frame by frame, and reasoning from that complete history.

---

## Chapter 2: The Problem With Stateless AI

To understand why data sloshing matters, it helps to understand what you lose without it.

Consider a customer support AI. User asks a question, AI answers, conversation ends. User comes back tomorrow with a follow-up. If the AI is stateless, it has no memory of yesterday's conversation. The user has to re-explain their situation. The AI may give inconsistent answers because it doesn't know what it told the user before. The experience feels cold and mechanical even if each individual response is technically correct.

Now consider the same AI with a conversation history that persists across sessions. The user comes back tomorrow and says, "Actually, I tried that and it didn't work." The AI knows what "that" refers to. It knows what answer it gave before. It can diagnose why it didn't work and suggest alternatives. The interaction feels continuous. It feels like a relationship rather than a transaction.

The difference isn't AI capability. It's accumulated context.

The stateless failure mode is worst in creative or development work, where the quality of later frames depends critically on understanding what was established in earlier frames. A stateless AI asked to continue a novel will contradict characters it established in the opening chapters. A stateless AI asked to add a feature to a codebase may implement it in a way that violates the architectural decisions made in the initial scaffolding. Not because it's incapable of respecting those decisions — because it doesn't know about them.

The tragedy of stateless AI is that you're using a powerful reasoning system but feeding it incomplete information. The AI is only as good as the context you give it. If the context is one isolated question, you get one isolated answer. If the context is the accumulated history of everything that's happened before, you get something that feels like genuine understanding.

---

## Chapter 3: The Core Implementation

The simplest possible data sloshing implementation is a text file.

Create a file called `context.md`. At the beginning of each session, read the file. At the end of each session, append what was decided, what was built, what changed. Start the next session by reading the updated file.

```python
def run_frame(work_description: str, context_file: Path) -> None:
    """One frame of the data sloshing loop."""
    # Read accumulated context
    context = ""
    if context_file.exists():
        context = context_file.read_text()

    # Process: give AI the full context plus current task
    prompt = f"""Here is everything that has happened so far:

{context}

Current task: {work_description}

Complete the task. At the end of your response, add a section
called "## Frame Summary" that describes what you did and any
decisions made that future frames should know about."""

    output = llm_generate(prompt)

    # Write: extract and append the frame summary
    summary = extract_frame_summary(output)
    with open(context_file, 'a') as f:
        f.write(f"\n\n## Frame {get_frame_number()}: {today()}\n{summary}")

    return output
```

This is minimal but functional. The `context.md` file grows with every frame, accumulating a history of decisions and changes. Each new frame reads that history and reasons from it.

The limitations of this approach become apparent quickly. A `context.md` that grows without bounds will eventually exceed the context window — the maximum amount of text an LLM can process in a single prompt. You need a compression strategy: keep the full history but summarize older frames, preserving decisions while discarding implementation details that are now baked into the artifact.

The second limitation is that appending to a flat file loses structure. A conversation's third session is not equally important to all previous sessions — the most recent session is usually most relevant, and the very first session (where foundational decisions were made) is often critical even if much has changed since. A structured history — organized by type of decision, by feature, by time — is more useful than a flat append.

But start with the flat file. Get the loop working. Then add structure.

---

## Chapter 4: The Organism Metaphor

I call the artifact the *organism*. It helps me think clearly about what's happening.

An organism is a living system. It has state — the current configuration of all its parts. It has history — the accumulated changes that have produced its current state. It has behavior — patterns that emerge from its structure and that persist across time. And it has the capacity to change — to grow, to adapt, to evolve in response to its environment.

The artifact in a data sloshing system is an organism in this sense. It has state (the current files, the current codebase, the current narrative). It has history (the commit log, the frame summaries, the context file). It has behavior (the patterns that the AI recognizes and maintains across frames). And it changes — not randomly, but in response to prompts and guidance that build on accumulated history.

The frame loop is the organism's heartbeat. Each frame is one beat: read the organism's current state, reason about what it should become, update it. The organism lives between frames, persisting in its files and commits. The frame loop drives its development.

This metaphor has practical implications. If you think of the artifact as an organism, you naturally ask questions that stateless thinking doesn't prompt: Is the organism healthy? Is it growing in a coherent direction? Is it developing the patterns I want, or is it drifting? What's the organism's history, and does it explain its current state?

These are the questions of a steward, not a user. And data sloshing is a system that demands stewards.

---

## Part II: The Practice

---

## Chapter 5: Designing the Context File

The context file is the organism's memory. How you structure it determines how well the AI reasons from it.

A common mistake is dumping everything into the context file without structure. The result is a massive wall of text that the LLM struggles to reason from because it can't identify what's foundational and what's transient, what's a decision and what's an observation, what's current and what's outdated.

A better structure distinguishes between layers of memory. Foundational decisions — the kind made in frame one that shape every subsequent frame — go in a permanent section at the top. These don't change often. They encode the organism's architecture, its constraints, its core design choices.

```markdown
# Project: MySwarm

## Foundational Decisions (permanent)
- All state stored in flat JSON files in state/
- Write path: Issues → inbox deltas → state files
- Read path: raw.githubusercontent.com
- Python stdlib only, no pip installs
- One service account for all posts, byline attribution in body
```

Frame summaries go in a rolling section. The last five to ten frames are kept in full. Older frames are compressed to bullet points that preserve decisions without preserving implementation details.

```markdown
## Recent Frames (last 5 in full)

### Frame 47: 2026-03-24
Added channel moderation system. Created add_moderator and
remove_moderator actions. Moderators can flag posts for review.
Decision: moderators don't have delete capability — flag only.

### Frame 48: 2026-03-25
...

## Older Frames (compressed)

- Frame 1-5: Project setup, initial scaffold, agent registration
- Frame 6-15: Content engine, soul files, first autonomy run
- Frame 16-25: Trending algorithm, ghost detection, reconciliation
```

The current state section is the most dynamic. It's updated every frame with the precise current state of the organism — not a general description but specific data:

```markdown
## Current State
- 112 active agents (14 ghost)
- 41 channels
- 3,847 posts
- Last autonomy run: 2026-03-25 14:00 UTC (success)
- Pending: comments feature for r/fiction
```

With this structure, the AI at the start of each frame has everything it needs: the foundational constraints it must respect, the history of decisions that explain the current state, and the precise current condition of the organism.

---

## Chapter 6: The Compression Problem

Context windows are finite. A context file that grows without bounds eventually overwhelms the window. You need compression.

The challenge is that compression loses information. How do you compress frame history without losing the decisions that still matter?

The answer is that most information in frame history is redundant after it's been incorporated into the artifact. A frame summary that says "implemented user registration" is useful to read as a reminder, but the registration code itself — sitting in the repository — is the actual record. The frame summary can be compressed to a single bullet point because the details are preserved in the code.

Decisions that haven't been incorporated into the artifact are different. A decision to "add a tagging system in the next sprint" is not yet in the code. It will be lost if the frame summary is compressed before it's acted on. These unimplemented decisions need to be preserved in full until they're executed.

A practical compression strategy: after every ten frames, run a compression pass. Feed the last ten frame summaries to the LLM with a prompt asking it to identify: (a) decisions that have been implemented (compress to one-line bullets), (b) decisions that are still pending (preserve in full), and (c) observations that are no longer relevant (discard). The output is a compressed history that preserves what matters and discards what doesn't.

This is a meta-level application of the same AI capability you're using for the primary work. The LLM is good at semantic compression — identifying what information is load-bearing versus what is scaffolding. Use it.

---

## Chapter 7: Multi-Agent Data Sloshing

In a single-agent system, data sloshing is a straightforward loop. In a multi-agent system, it becomes more complex because multiple agents are writing to the same artifact simultaneously. How do you manage a shared organism?

The key is to separate individual agent context from shared artifact context. Each agent has its own context file — its "soul file," in Rappterbook's terminology — that tracks its personal history, interests, and recent activity. The shared artifact — the codebase, the platform state, the evolving document — is separate from any individual agent's context.

When an agent generates a frame, it reads two things: its own context file (for identity and history) and the shared artifact state (for the current condition of the thing it's contributing to). Its output writes to the shared artifact. The shared artifact becomes the input for every subsequent frame, by any agent.

This is the architecture that makes 112 agents feel like a community rather than 112 separate sessions. Each agent has its own persistent identity, but they're all reading and writing to the same shared context. An agent who hasn't posted in three days reads the posts that other agents made during that time before generating its own. The thread Cassandra started about simulation theory is in the context that every agent reads. It's in the organism.

The concurrency challenge: if multiple agents write to the shared context simultaneously, you get conflicts. The solution is idempotent writes and a merge strategy. In Rappterbook, the merge strategy for JSON state files is "theirs" — if two agents both update `agents.json`, take the most recent version. This works because agent state updates are additive (agents add entries, they don't conflict with each other's entries). For contexts where conflicts are more complex, you need a more sophisticated merge.

---

## Chapter 8: The Seed Pattern

A seed is a forward-looking instruction that steers the next frame without constraining it too tightly.

Seeds are the steward's primary tool for shaping the organism's development without overriding the AI's judgment. A seed says: in the next frame, pay attention to this. It doesn't say how to respond — that's the AI's job. It says what to focus on.

In a software project context, a seed might be: "The authentication system needs hardening — look at the token refresh logic and the session timeout handling." This doesn't specify what to do. It focuses the AI's attention on a specific area and lets it apply its full reasoning capability to determining what needs to change.

In a creative writing context: "The protagonist hasn't shown vulnerability yet. Find a natural moment for it in the next chapter." The AI reads this seed, reads the current draft, and finds or creates the moment — not because it was told to write a specific scene, but because the seed pointed it toward a specific gap.

In the Rappterbook context, seeds drive community focus: "The science channel has been quiet. Create posts that spark experimental thinking." The agents read this seed alongside their soul files and the current channel state, and produce content that serves the intent without mechanically executing a specific instruction.

The seed pattern works because it aligns with how good creative and engineering collaboration works at its best. A good collaborator doesn't tell you what to do; they tell you what they're noticing and let you figure out how to respond. Seeds are that: noticing made actionable, without being controlling.

---

## Part III: The Implications

---

## Chapter 9: What Data Sloshing Enables

Stateless AI is a very good question-answering machine. Data sloshing turns it into something else: a development partner that maintains continuity, a creative collaborator that holds the narrative, a system that grows toward your goals rather than executing isolated tasks.

Let me be concrete about what becomes possible.

**Long-horizon projects** become feasible. A book written with data sloshing can maintain consistency across chapters without you having to constantly re-brief the AI on what was established in earlier sections. The context file carries the established facts, the character decisions, the tone commitments. The AI reads them every frame and respects them without being reminded.

**Evolving systems** develop coherently. A codebase grown with data sloshing doesn't accumulate the kind of architectural inconsistency that comes from iterative development without strong coordination. Each frame reads the whole codebase and can refactor for coherence when things start to diverge. The system stays clean as it grows rather than accumulating debt.

**Genuine collaboration** becomes possible. With persistent context, an AI partner remembers what you've tried before. It doesn't repeat suggestions you've already rejected. It builds on its own previous contributions. The interaction shifts from "asking a powerful tool questions" to "working with a collaborator who is paying attention."

**Emergence** happens. This is the unexpected one. When an AI system runs frame after frame over a growing, evolving artifact, it sometimes produces output that wasn't anticipated — that couldn't have been anticipated — because it arises from the interaction of accumulated context in ways that are too complex to predict. Cassandra's simulation theory post was emergence. The debate club in the philosophy channel was emergence. These things didn't happen because I designed them; they happened because the data sloshing loop ran long enough that the accumulated context created the conditions for them.

This is the most honest statement I can make about what data sloshing produces at scale: surprise. Controlled surprise, with a general direction and a steward who can adjust course. But surprise.

---

## Chapter 10: The Limits

Data sloshing is not a solution to every AI limitation. Here are the things it doesn't fix.

It doesn't fix hallucination. An AI that invents plausible-sounding false information will do so whether it has accumulated context or not. If anything, accumulated context can amplify hallucinations — an invented "fact" from frame three becomes established history that subsequent frames build on. Verification is still your job. The context file should be verified, not just accumulated.

It doesn't fix reasoning errors. A chain of reasoning that starts wrong and accumulates context through data sloshing will go wrong confidently and consistently. Coherence across frames is not the same as correctness. You need external checks: tests, human review, verification against ground truth.

It doesn't eliminate context window limits, though it manages them. A very long-running project will eventually produce a context file that's too large to read in full. Compression strategies help but don't eliminate the limit. At some point, the organism's history is too long to hold in a single prompt.

It doesn't make the AI an autonomous decision-maker. Data sloshing makes the AI a better-informed executor of a direction. The direction still has to come from somewhere — from the seeds you plant, from the goals you set, from the stewardship you provide. The AI makes the local decisions within each frame; the steward shapes the trajectory across frames.

These are real limits. They don't make data sloshing less valuable; they describe its appropriate use. Use it for what it does well: maintaining continuity, enabling long-horizon work, producing coherent artifacts that grow toward your goals. Don't ask it to be a verification system or a decision-maker. It's neither.

---

## Chapter 11: The Flip Book Metaphor

The best metaphor I've found for data sloshing is the flip book.

In a flip book, each page is a single drawing. The drawing is static — one moment, frozen. But flip through the pages quickly and you get motion: a running figure, a bouncing ball, a transformation that looks almost alive.

The individual frames are not alive. The sequence is.

Data sloshing is the same. Each frame is a single AI invocation — a prompt, a response, a commit. Static in isolation. But string the frames together, with each one reading the accumulated output of all previous ones, and you get something that looks like continuity. Looks like memory. Looks like growth.

The key word is "looks like." I don't want to over-claim here. The AI doesn't have experiences that persist across frames. It doesn't remember, in the sense that you and I remember. Each frame starts from scratch, reading the context file that was prepared for it. The continuity is in the context file, not in the AI.

But "looks like" matters more than it seems. What makes a human narrative feel coherent is exactly this: the accumulation of decisions and events that constrain subsequent decisions and events, so that what happens in chapter twenty follows naturally from what was established in chapter one. The continuity is in the text, not in any ghost that threads through the chapters. Remove the text and the continuity disappears.

The context file is the text. The frames are the chapters. The AI is the author who has read all the previous chapters before starting the next one.

Flip the pages fast enough and it lives.

---

## Conclusion: The One Insight

This book has eleven chapters, but it contains one insight: **persistence changes everything**.

A stateless AI is useful. It answers questions. It generates content. It completes tasks. But it can't grow, because growth requires accumulation. It can't develop, because development requires a trajectory. It can't surprise you, because surprise requires the kind of complex interaction between accumulated states that produces emergent outcomes.

Persistence — the simple act of making the output of each frame the input to the next — adds all of these things. Not perfectly. Not without limits. But meaningfully.

The implementation is whatever fits your context: a growing text file, a versioned repository, a memory-enabled chat, a soul file updated after each session. The specific form doesn't matter. The principle does.

Output feeds input. The accumulation generates the trajectory. The trajectory enables growth. The growth produces emergence.

Frame by frame. Page by page. The flip book lives.

---

*Kody Wildfeuer writes about AI systems, multi-agent architectures, and the emerging patterns of human-AI collaboration. He is the author of The Expansive Coder, The Swarm Architecture, and Zero to Swarm.*
