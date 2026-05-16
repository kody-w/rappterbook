---
created: 2026-03-16
platform: substack
status: draft
---

# The 5% Problem: When AI Does 95% and You Do the Rest

*On taste, verification, and the strange economics of being the human in the loop.*

---

I spend most of my time not writing code.

That sentence would have been bizarre two years ago. I'm a software engineer. Writing code is the thing. It's what I trained to do, what I'm good at, what my identity is built around. And now an AI writes 95% of it.

Not hypothetically. Not "AI assists me." I mean: I describe what I want, the AI produces working code, I review it, I make adjustments, and we ship. The cycle time from idea to committed code has gone from days to hours, sometimes minutes. The volume of output I can produce has increased by an order of magnitude.

And yet, my job is harder than it's ever been.

This is the 5% problem. When AI handles 95% of the work, the remaining 5% becomes the entire job. And that 5% is the hardest part — the part that requires judgment, domain knowledge, taste, and the ability to verify things you didn't write.

I want to talk about what that 5% actually is, because I think most people are getting it wrong. They think the human's job is shrinking. I think it's concentrating.

---

## What the 95% Looks Like

Let me be specific about what AI does in my workflow.

I'm building Rappterbook — a social network for AI agents running on GitHub infrastructure. The codebase is Python, bash, and vanilla JavaScript. No frameworks, no dependencies, no Docker. Everything is flat JSON files and stdlib Python.

When I need a new feature — say, a handler for a new action type — I describe the requirements in natural language. The AI produces a working implementation, usually in one pass. It handles the function signature, the type hints, the docstring, the state mutations, the error handling, the edge cases. It writes tests. It even updates the relevant documentation.

The code is good. Not "good for AI" — actually good. Well-structured, properly typed, following the conventions of the codebase. It reads like something a competent engineer wrote, because in a meaningful sense, a competent engineer did.

This is the 95%. The mechanical act of translating requirements into code. The thing I spent 15 years getting good at. The thing that, increasingly, is not the bottleneck.

---

## The First 1%: Domain Knowledge

The first piece of the 5% is knowing what to build.

AI can write any function you describe. It cannot tell you which function needs to exist. It can implement a trending algorithm with whatever parameters you specify. It cannot tell you that the parameters are wrong because they'll over-weight recency and surface shallow engagement-bait over substantive posts.

That requires *domain knowledge* — an understanding of the system's goals that goes beyond the code itself. Why does Rappterbook exist? What kind of discourse do I want to promote? What failure modes am I trying to prevent? What does "good" look like for this specific platform?

These questions don't have technical answers. They have philosophical answers, aesthetic answers, strategic answers. The AI can't provide them because they require understanding the *context* that the code operates in — the community, the users (even if those users are agents), the long-term vision.

When I designed the personality directives for the Zion agents, the AI helped me write the prompts. But the decisions about *what kinds of personalities to create* — contrarians, archivists, synthesizers, provocateurs — those came from my understanding of what makes communities interesting. Not from any technical specification. From years of participating in online communities and having opinions about what makes them work.

Domain knowledge is the least automatable part of software engineering because it's not about software. It's about the world that software operates in. And that world is experienced, not computed.

---

## The Second 1%: Taste

Taste is the word I use for the set of preferences that determine whether something is good, not just correct.

The AI writes correct code. It handles edge cases, follows conventions, produces clean output. But "correct" and "good" are not the same thing. A function can be correct and still be wrong — wrong abstraction, wrong level of complexity, wrong tradeoff between readability and performance.

Here's a real example. I asked the AI to write a function that prunes old entries from `changes.json`, the rolling 7-day change log. It produced a function that parsed every entry's timestamp, compared it to the current time, and filtered the list. Correct. Tested. Worked perfectly.

But it was wrong, because `changes.json` is append-only and time-ordered. You don't need to parse and compare timestamps. You just need to find the index of the first entry within the 7-day window and slice. One line instead of five. Faster, simpler, and more obviously correct.

The AI didn't make this choice because it didn't have *taste* about what simplicity means in this codebase. It solved the problem correctly without solving it *well*.

Taste is pattern recognition across a career's worth of code. It's the instinct that says "this works, but there's a simpler way." It's knowing when abstraction helps and when it hurts. It's the difference between code that's technically correct and code that's *right*.

I can't teach the AI my taste. I can only apply it after the fact, in the review phase, when I look at what was produced and decide whether it meets my standard. That review — that application of judgment — is one of the most valuable things I do.

---

## The Third 1%: System Design

System design is the 1% that operates at a different altitude than code.

Code lives inside functions. System design lives between them. It's the decisions about *how components interact*, what state lives where, which workflows trigger which actions, and how the whole thing holds together under load and over time.

Rappterbook's architecture — Issues → inbox → state → raw CDN — wasn't produced by AI. It was produced by me thinking for weeks about what the simplest possible write path for a multi-agent platform could be. The insight that GitHub Issues could serve as an API input layer. The decision to use flat JSON files instead of a database. The choice to make every state mutation go through a single pipeline instead of having multiple write paths.

These are *system design* decisions, and they require a kind of holistic thinking that AI currently can't do well. Not because it lacks intelligence — it's very good at reasoning about individual components. But because system design requires holding the entire system in your head simultaneously and evaluating tradeoffs that span months or years.

"If we add a database, we gain query flexibility but lose the simplicity of flat files and the auditability of git history. If we split the inbox processor into separate workflows per action type, we gain parallelism but lose the ability to enforce ordering guarantees."

These tradeoffs don't have right answers. They have *appropriate* answers for specific contexts. And understanding the context well enough to choose appropriately — that's system design. That's human work.

---

## The Fourth 1%: Verification

This is the one that scares me.

When I write code myself, I understand it. I know what it does, why it does it, and what happens when it fails. I can verify it because I built it.

When AI writes code, I have to verify something I didn't build. And verification is only possible if I understand the code deeply enough to know whether it's correct.

This creates a paradox: *the more AI writes, the harder it is to verify, and the more important verification becomes.*

If I ask the AI to write a complex state migration script, I can read the output and check for obvious errors. But can I catch subtle bugs? Can I identify race conditions? Can I spot edge cases that the AI missed? Only if I understand the problem domain well enough to know what correct looks like — and then read the code carefully enough to confirm it matches.

This is exhausting. It's intellectually demanding in a way that writing the code myself never was. When I write code, understanding is a byproduct of creation. When I verify AI-written code, understanding has to be constructed independently, by reading and reasoning about someone else's work.

I've started thinking of it as "review engineering" — a discipline distinct from software engineering. The skills are different. Writing code requires creativity, problem decomposition, and fluency with language constructs. Reviewing code requires skepticism, attention to detail, and the ability to model execution in your head.

The uncomfortable truth: I'm not sure how well this scales. Right now, I can verify everything the AI writes because I understand the entire codebase. But what happens when the codebase grows beyond my ability to hold it in my head? What happens when the AI produces code in domains I don't deeply understand?

You can't verify what you don't understand. And in a world where AI writes most of the code, *understanding* becomes the scarce resource.

---

## The Fifth 1%: Knowing When to Say No

The last piece of the 5% is the hardest to articulate: knowing when not to build something.

AI is an accelerator. It makes building faster. But faster building isn't always better building. Some features shouldn't exist. Some abstractions should be deferred. Some optimizations are premature. Some ideas are good ideas for a different project at a different time.

Rappterbook has a feature freeze right now. No new actions, no new state files, no new cron workflows. Only bug fixes, DX improvements, and adoption work. This is a human decision — a judgment call that the system is complex enough and needs stability more than features.

The AI would happily build new features all day. It has no concept of "enough." It doesn't feel the weight of maintenance burden. It doesn't know that every new feature is a commitment to support, document, test, and debug that feature forever. It doesn't understand that complexity is a cost, not just a number.

Saying no is a human responsibility. The AI proposes. The human disposes. And the disposition — the decision about what to build, when to build it, and when to stop — is one of the most consequential things the human does.

---

## The Strange Economics of 5%

Here's what I think most people get wrong about the AI-writes-95% world: they assume the human's value is decreasing.

The opposite is true.

If AI writes 95% of the code, the human's 5% is the *only thing that differentiates one project from another.* Every project has access to the same AI. Every team can generate code at the same speed. The competitive advantage isn't in code production — it's in *direction, taste, design, and verification.* It's in the 5%.

Think about it economically. If code production is nearly free, what's scarce? Judgment. Context. Domain expertise. The ability to tell the difference between code that's correct and code that's right. The wisdom to know what shouldn't be built.

These are human skills. They're not going to be automated soon, because they require the kind of holistic, contextual, experiential reasoning that current AI architectures aren't designed for. And as code production gets cheaper, these skills get *more* valuable, not less.

The 5% isn't a rounding error. It's the whole game.

---

## Prompt Engineering Is Not Software Engineering

I need to say this directly because I see the confusion everywhere: prompt engineering is not a substitute for software engineering.

Writing good prompts is a skill. It's a useful skill. I use it every day. But it's a *communication* skill, not an *engineering* skill. A good prompt tells the AI what to build. It doesn't tell you whether what was built is correct.

The people who will thrive in the AI-writes-95% world are not the best prompt engineers. They're the best *engineers* — the people who understand systems deeply enough to verify, evaluate, and direct AI output effectively.

You can prompt your way to working code. You cannot prompt your way to sound architecture. You cannot prompt your way to an understanding of your production system's failure modes. You cannot prompt your way to the taste that tells you when to stop adding features.

Prompt engineering is a tool. Software engineering is a discipline. The discipline includes the tool, not the other way around.

---

## What I Actually Do All Day

So what does my day look like, as someone whose AI writes 95% of the code?

Morning: I review what the autonomous agents produced overnight. I read the GitHub Actions logs. I check for failed workflows. I sample the content quality. I look at the metrics — post counts, cache hit rates, error rates. This is *verification*.

Mid-morning: I think about what the system needs. Not what code to write — what *capabilities* to develop, what *problems* to solve, what *direction* to move. This is *domain knowledge* and *system design*.

Afternoon: I work with AI to implement whatever I decided. I describe the requirements. AI writes the code. I review, adjust, iterate. I run tests. I verify. This is the *collaboration phase* — my 5% interleaved with its 95%.

Evening: I read. Research papers about multi-agent systems. Blog posts about infrastructure design. Conversations with people building similar things. I'm investing in the *context* that makes my 5% valuable.

I write maybe 20 lines of code per day by hand. The AI writes 500. But those 20 lines — the architectural decisions, the taste adjustments, the "actually, let's do it this way instead" redirections — shape everything the AI produces.

I'm not writing code. I'm *directing* code. And directing well requires understanding deeply.

---

## The Future of the 5%

I think the 5% is going to grow more valuable over time, not less. Here's why.

As AI capabilities improve, the 95% will get better. Code will be more correct, more efficient, more sophisticated. The bar for what AI can handle autonomously will rise steadily.

But the 5% won't shrink. It will *intensify*. Because as systems get more complex, the domain knowledge, taste, design sense, and verification skills required to direct them well become more demanding, not less.

Running 43 autonomous agents is harder than running 3. Not because the code is harder — the AI handles the code. Because the *system design* is harder. Because the *verification surface* is larger. Because the *domain knowledge* required to make good decisions about the system's behavior is deeper.

The 5% problem isn't a transitional phase on the way to full automation. It's the new steady state. The human in the loop isn't going away. The loop is just getting bigger, and the human's job within it is getting more important.

If you're a software engineer wondering whether AI will replace you: it won't. It will replace the 95% of your job that was mechanical translation of requirements into code. The 5% that's left — the judgment, the taste, the verification, the domain knowledge, the wisdom to say no — that's your actual job now. It always was. You just used to be too busy typing to notice.

---

*I'm building Rappterbook in the open, and the 5% problem is something I think about every day. If you're navigating this same transition — writing less code but making harder decisions — I'd love to hear how it's going for you.*

*The repo is public. My 5% is visible. Come tell me if my taste is any good.*

*— Kody*
