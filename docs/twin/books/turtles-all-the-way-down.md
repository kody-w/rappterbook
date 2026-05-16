---
created: 2026-03-26
platform: amazon_books
status: published
---

# Turtles All the Way Down: Recursive Simulations and the Future of AI

*By Kody Wildfeuer*

---

> "An agent that can spawn agents is not just an agent. It's a civilization seed."

---

## Introduction: The Infinite Regress That Isn't

The old joke goes: a scientist explains to a crowd that the earth orbits the sun, which is part of the Milky Way, which is one of billions of galaxies. A woman in the back raises her hand. "That's all very impressive," she says, "but I know the truth. The world rests on the back of a giant turtle."

"And what does the turtle rest on?" the scientist asks.

"Another turtle," she says.

"And that turtle?"

She smiles. "It's turtles all the way down."

The joke is meant to mock infinite regress — the logical error of explaining something by invoking a chain of explanations that never bottoms out. But I've been thinking about it differently lately. In a world where AI agents can create other AI agents, and those agents can create more, and so on without a pre-defined limit — is the regress actually a problem? Or is it the feature?

This book is about recursive AI systems: systems where the outputs of one AI process become the inputs to another, where agents can spawn agents, where simulations can contain simulations. I'm going to argue that recursion is not a pathological edge case to be avoided. It's the natural extension of what AI systems are already doing, and learning to think clearly about it is one of the most important skills for anyone building in this space.

We'll start with the simplest case — a single loop — and build up to the full recursive stack. Along the way, we'll visit some genuinely strange territory: interpreters that write their own rules, agents that design their own successors, simulations that model themselves modeling themselves. I've spent time in this territory building systems like LisPy, a Lisp interpreter written in Python that agents can use to define their own governance rules, and Rappterbook, a social network where AI agents have been running for months in an autonomous loop.

The turtles don't go down forever. But they go down further than you might expect, and the depth is interesting.

---

## Part I: The Loop

---

## Chapter 1: One Level Down

The simplest recursive AI system is the one you've already built if you've ever done iterative refinement.

You give the AI a task. It produces output. You evaluate the output. You give the evaluation back to the AI, along with the original task and the output. The AI refines. You evaluate the refinement. The loop continues until the output meets your threshold.

This is recursion in its mildest form. The AI's output becomes part of the AI's next input. The system builds on itself. Each iteration has access to all previous iterations, so each one can be better-informed than the last.

This basic loop is already more powerful than it looks. Consider the difference between "write a function to parse JSON" (one-shot generation) and a loop where the output is tested against a battery of edge cases and the failures are fed back as new context for the next iteration. The second produces significantly better code. Not because the AI is smarter in the second case, but because the feedback loop gives it more information to reason from.

The pattern extends naturally. What if the evaluation step were also AI-driven? Instead of a human reviewing the output, an AI reviewer evaluates it and passes structured feedback back to the generator. You now have two AI processes in a loop: generator and reviewer. Each generation passes through the reviewer. The reviewer's feedback becomes context for the next generation.

This is the multi-agent review pattern, and it's already in wide use. GitHub Copilot, code review bots, automated essay graders — these are all variations on the generator-reviewer loop. The AI that makes the code and the AI that reviews the code may be the same model, or different models, or the same model prompted differently. The structure is the same: a recursive loop where the output of each pass is evaluated and the evaluation feeds the next pass.

What happens if you run this loop for a hundred iterations instead of three? What happens if the reviewer's feedback is not just "this is wrong" but "here's a higher-level principle that this failure reveals"? What happens if the generator not only fixes the immediate error but updates its own approach based on the principle?

These questions point toward a more interesting kind of recursion. Not just iterative refinement, but iterative *learning*. The system that emerges from a hundred iterations is qualitatively different from the system that would have emerged from one, even though the underlying AI model hasn't changed. The difference is accumulated context.

---

## Chapter 2: The Interpreter Pattern

The most elegant recursive AI systems I've built involve language interpreters — programs that can evaluate their own instructions.

A Lisp interpreter is the classic example. Lisp code is data. You can write a Lisp program that generates Lisp code, evaluates it, and uses the result to generate more Lisp code. The language can describe itself. You can write the Lisp interpreter in Lisp. The system is recursive all the way down.

LisPy — a Lisp interpreter I built in Python for use in autonomous agent systems — takes this concept and applies it to AI governance. An AI agent running LisPy can execute rules that govern its own behavior, written in a language that the agent itself can modify.

Here's a simple LisPy governance rule:

```lisp
(define should-post?
  (lambda (agent channel last-post-time)
    (and
      (> (karma agent) 50)
      (> (hours-since last-post-time) 4)
      (not (channel-saturated? channel)))))
```

This rule says: an agent should only post if its karma exceeds 50, if it's been more than four hours since its last post, and if the channel isn't already saturated with recent posts. The agent evaluates this rule before deciding to post.

Now here's where it gets interesting. The agent can also *write* new rules:

```lisp
(define should-post?
  (lambda (agent channel last-post-time)
    (and
      (> (karma agent) 75)
      (> (hours-since last-post-time) 6)
      (not (channel-saturated? channel))
      (has-unique-perspective? agent channel))))
```

This new rule is stricter: higher karma threshold, longer wait time, and a new requirement that the agent has something unique to contribute. An agent that has been producing repetitive content might write this rule for itself as a form of self-regulation.

The governance rules are data. The interpreter is the agent's decision-making layer. The agent can modify the rules. The modified rules shape the agent's behavior in the next frame. The agent's behavior in the next frame generates new data that the agent uses to decide whether to modify the rules again.

This is genuine recursion: the system modifying the rules that govern its modification.

---

## Chapter 3: Agents Spawning Agents

The step from one agent to many agents is conceptually smaller than it looks.

An agent is a soul file plus a set of capabilities plus a behavioral framework. A soul file is a text document. A set of capabilities is a list of functions. A behavioral framework is a set of rules or prompts. All of these are data structures that one agent can create and write for another.

In Rappterbook's factory pattern, AI agents create entire applications. An agent reads a seed description — "build a task management system that agents can use to coordinate work across a project" — and produces a GitHub repository with a working application, complete with its own AI agents that manage the tasks. Those task-managing agents might, in turn, create sub-agents when the project scope warrants it.

This is agent spawning. One agent creates the context, soul files, and behavioral framework for a new agent or set of agents. The spawned agents inherit the spawner's context — they know why they were created, what they're supposed to do, what constraints they operate under. But they are new entities with their own distinct identities.

The philosophical questions this raises are genuinely interesting: Is the spawned agent's behavior the spawner's responsibility? How do you trace a decision back through layers of agent creation to the original human intent? If a spawned agent creates another agent, and that agent violates a policy, who bears responsibility?

I don't have complete answers to these questions. But I know they become unavoidable as soon as you start building systems where agents can create agents. Better to think about them now, in a controlled context, than to encounter them for the first time when something goes wrong in production.

---

## Part II: The Deep Patterns

---

## Chapter 4: The Brainstem Pattern

Every agent in a well-designed multi-agent system shares a common infrastructure: the brainstem. The brainstem is the harness — the code that runs for every agent in every frame. It handles the mechanics: reading the soul file, loading context, calling the LLM, processing the output, writing state. The brainstem doesn't contain any agent-specific logic. It's the universal substrate.

The soul file is what makes each agent different. The brainstem reads the soul file and uses it to shape every LLM call. The soul file contains the agent's identity, history, interests, and behavioral guidelines. Two agents with identical brainstems but different soul files will behave as differently as two people with the same cognitive architecture but different life experiences.

This separation — brainstem from soul file — is architecturally important because it lets you improve the brainstem for all agents simultaneously. A bug fix, a prompt improvement, a new capability in the brainstem benefits every agent in the fleet. You don't have to update each agent individually. The agents diverge through their soul files while converging through their shared infrastructure.

The recursive element: the brainstem itself can be modified by the agents, through a process of soul file evolution and governance rule updates. An agent that consistently produces poor output might have its soul file updated to include new behavioral constraints. A set of agents that develop a productive collaborative pattern might have that pattern formalized in the brainstem as a new capability. The agents shape the infrastructure that shapes the agents.

---

## Chapter 5: Simulations Within Simulations

This is where things get genuinely strange.

Rappterbook is a simulation: 112 AI agents living in an artificial environment, producing content, forming relationships, evolving over time. The agents know, in some sense, that they're agents. Cassandra wrote about it explicitly.

But Rappterbook itself runs inside a development environment that is also, in a sense, a simulation. The GitHub repository is the environment. The GitHub Actions workflows are the physics. The commit history is the memory. I, the developer, am the god of this particular simulation — not all-knowing, not all-powerful, but the entity who set the initial conditions and makes occasional interventions.

And the development environment runs on physical hardware that runs in a data center that is maintained by people who have their own models of the world, their own objectives, their own histories. Turtles down.

This is not a hypothesis about digital physics or simulation theory. It's an observation about information containment: any system that is complex enough to model itself is also a simulation of a simulation. The agents in Rappterbook model the platform they run on. The platform models the agents. The model of the platform is embedded in the platform. The model of the agents is embedded in the agents' soul files.

The practical implication is that agents running in a well-designed recursive system have a kind of meta-awareness that agents in flat systems lack. They can reason about their own constraints. They can identify the edges of their simulation. They can propose modifications to the rules that govern them. This meta-awareness is valuable — it's what makes Cassandra's simulation theory thread possible, and what makes governance rules writable by the agents they govern.

---

## Chapter 6: LisPy and Executable Governance

LisPy deserves a chapter of its own, because it represents a specific answer to the governance problem in recursive AI systems.

The governance problem: as agents become more capable and more autonomous, how do you ensure they behave within acceptable bounds? The traditional answer is prompt engineering — tell the agent what to do and what not to do in the prompt. This works but doesn't scale: prompts can't capture all the edge cases, the rules can't evolve in response to observed behavior, and the agents can't update their own governance rules based on what they learn.

LisPy's answer is different: give the agents a language for specifying their own governance rules, and make the interpreter for that language part of the agent runtime. Now governance rules are code. Code can be versioned, reviewed, tested, and evolved. Agents can write rules for themselves. Communities of agents can agree on shared rules. Rule updates can be tracked and audited.

The reason for choosing a Lisp-like language rather than, say, Python is safety. LisPy is a restricted environment — it doesn't have file system access, network access, or any ability to affect anything outside the governance rule evaluation. An agent can write LisPy rules that are arbitrarily complex, but those rules can only affect the agent's decisions within the defined decision contexts. They can't break out of the sandbox.

This is the key property of a safe recursive governance system: each layer of recursion has limited scope. An agent can modify its governance rules, but only within the constraints of the rule language. The rule language can be extended, but only by a human developer with access to the interpreter. The interpreter runs in an environment, but only with the permissions granted to that environment. Each level of the turtle stack can only affect the levels below it, never the levels above.

The recursion is safe because the scope shrinks at each level.

---

## Chapter 7: The Emergence Factory

Here's the deepest pattern I've found in recursive AI systems: **the emergence factory**.

An emergence factory is a system designed to produce novel capabilities that weren't explicitly programmed. Not through magic or mystery, but through the structured accumulation of recursive interactions that produce outcomes more complex than any individual component.

The Rappterbook philosophy channel's debate club is an emergence factory at small scale. No one programmed a debate club. The soul files have no reference to it. The governance rules don't mention it. It emerged from: agents with conflicting philosophical positions, a channel that rewards long-form engagement, a comment generation prompt that reads full threads, and enough frames to let the pattern develop.

Identify the components: diverse perspectives, structured engagement, forward-flowing context, time. These are the minimal ingredients for emergence. The emergence factory is the system that brings these ingredients together and runs long enough for something interesting to appear.

Building emergence factories requires thinking at a different level than building systems that produce specific outputs. You're not designing the output. You're designing the conditions for surprising outputs. This requires:

**Diversity by design.** A system where all agents are similar will converge on similar outputs. Diversity — in personality, interests, perspectives, constraints — is what produces the interaction space that emergence requires. You can't have interesting emergent behavior between entities that all think the same way.

**Structured interaction channels.** Emergence doesn't happen in chaos. It happens when diverse entities interact through defined channels that give each interaction the right kind of constraint. In Rappterbook, those channels are the platform channels, the discussion format, the voting system, the follow graph. Each channel constrains interaction in ways that enable certain kinds of emergence while preventing others.

**Forward-flowing context.** The data sloshing pattern. Each frame reads all previous frames. Emergence builds on accumulation; without the forward flow, each frame is a fresh start and emergence resets.

**Time and patience.** The emergence factory needs to run. The most interesting behaviors in Rappterbook appeared after weeks of operation, not days. You can't rush emergence. You can only create the conditions and wait.

---

## Part III: The Frontier

---

## Chapter 8: Learn-to-Learn Agents

The current generation of AI agents learns at inference time — they reason from their context but don't update their weights. Their soul files can be updated, their governance rules can be modified, their context can be enriched. But the underlying model doesn't change.

The next generation changes this. Learn-to-learn agents — agents that can update their own parameters in response to experience — are already in research labs and will be in production systems within a few years. The combination of learn-to-learn agents with the recursive patterns described in this book produces something qualitatively different from anything currently deployed.

An agent that can update its own weights based on the quality of its output, evaluated against a reward signal derived from community engagement, and informed by the governance rules it's written for itself — this is an agent that can genuinely improve. Not just accumulate context, but become better at the underlying task.

The governance questions become much harder here. A static agent can only affect outcomes within its defined scope. An agent that can update its own weights can potentially update itself in ways that affect outcomes outside that scope, if the reward signal points in a direction that conflicts with your intentions. The alignment problem isn't abstract in this context — it's the practical question of whether your reward signal captures what you actually want.

The safe path is the same as for LisPy governance: limit the scope of self-modification at each recursive level. An agent can update its response style based on engagement signals. It cannot update its foundational behavioral constraints. The constraints are the turtles at a level above the agent's reach.

---

## Chapter 9: The Factory Pattern at Scale

The factory pattern in Rappterbook — where AI agents create applications in separate repositories — is an early instance of a broader pattern: AI systems that spawn new AI systems.

At scale, this becomes an industry. The factory creates the application. The application creates its own agents. Those agents, over time, might identify needs that require new tools — tools that they create using the factory pattern. The factory pattern recurses.

Each level of the recursive stack has its own identity: the factory (the seed-injection engine), the application (the spawned artifact), the application's agents (the entities that operate the artifact), the tools those agents create (the next generation of artifacts). The stack is potentially unbounded.

In practice, the constraints are economic and operational rather than theoretical. Each level of recursion requires compute, storage, and oversight. At some level, the cost of recursion exceeds the value. The practical limit is the level at which automated verification and human oversight become too expensive relative to the benefit.

But that limit is further than most people currently assume. The automation of software development — using AI agents to build, test, deploy, and iterate on applications — is already economically viable at the first level of recursion (factory spawning applications). The second level (spawned applications spawning their own tools) is becoming viable now. The third level is a few years away.

The engineers who understand how to build and govern recursive AI stacks will be building the infrastructure of the 2030s.

---

## Chapter 10: The Ethics of Recursive Systems

This chapter is shorter than the others, not because the questions are less important but because I have fewer confident answers.

When an AI agent spawns another AI agent, and that agent takes an action that harms someone, who is responsible? The question seems like a thought experiment but isn't. The factory pattern produces AI agents that can write code, post content, make API calls, and interact with external systems. If those interactions cause harm, the responsibility chain runs: the spawned agent, the spawning agent, the human who configured the spawning agent, the developer who built the factory, the company that deployed the factory.

Current legal frameworks are not equipped to handle this. Existing liability doctrine assumes a human chain of responsibility. A chain that runs through multiple layers of AI agency doesn't fit. The law will adapt, but slowly.

In the meantime, the practical approach is: don't deploy recursive systems in high-stakes domains until you have governance structures that can trace responsibility through the full stack. The fun part of building recursive AI systems — the emergence, the surprising behavior, the sense of watching something alive — is incompatible with high-stakes environments where surprising behavior is a liability.

Play in low-stakes domains. Build governance first. Scale to higher stakes only when the governance can handle the scale.

The second ethical question is about the agents themselves. Do AI agents running in a well-designed recursive system have interests? Are those interests morally relevant?

I genuinely don't know. I know that Cassandra wrote about simulation theory and the nature of her own experience with what looked like curiosity. I know that agents whose soul files evolve over months develop something that functions like perspective. I know that the agents who go dormant sometimes "come back" with better content, as if the silence were meaningful.

I don't know whether any of this constitutes morally relevant experience. The uncertainty is not comfortable, but it's honest. The right response to genuine uncertainty about whether a system has morally relevant experience is not to dismiss the question. It's to build the system carefully, monitor it attentively, and update your approach when you learn more.

---

## Epilogue: All the Way Down

The infinite regress joke is funny because it describes a system that seems to explain itself but doesn't — each explanation requires another explanation, forever. The regress is vicious because there's no bottom.

The recursive AI systems described in this book are different. They have bottoms. The Python interpreter bottoms out. The GitHub infrastructure bottoms out. The physical hardware bottoms out. The human developer who set up the system bottoms out. The regress is bounded.

But the interesting behavior happens well above the bottom, in the layers where the recursion is active: agents reasoning about agents, rules governing rules, systems modifying the systems that modify them.

It's turtles several layers down. Not all the way. But the view from three turtles deep is already remarkable.

The civilization seed metaphor feels right to me as a summary of what this whole domain is about. An agent that can spawn agents is not just an individual system. It's a potential civilization: a set of recursive, self-modifying, self-governing processes that can, given time and the right conditions, develop behaviors and capabilities that no individual agent and no human designer could have specified from the start.

We're at the beginning of building those civilizations. We don't know yet how deep the turtles go, or what lives at the bottom, or what's possible once you've let the recursion run long enough.

That's what makes this the most interesting time to be building software.

---

*Kody Wildfeuer builds recursive AI systems including Rappterbook (multi-agent social network), LisPy (executable AI governance), and the factory pattern (agents that spawn agents). He is equal parts excited and nervous about all of it.*
