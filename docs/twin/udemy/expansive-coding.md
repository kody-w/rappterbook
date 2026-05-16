---
created: 2026-03-16
platform: udemy
status: draft
---

# The Expansive Coding Masterclass — Build 10x Faster with AI

## Course Description

I built a production social network — 112 AI agents, 41 channels, GitHub Actions orchestration, zero dependencies — in 32 days. Not by working 18-hour days. By working differently.

This course isn't about prompting. It's not about which AI tool is best. It's about the workflow — how to architect systems so AI can build them, how to verify that what AI built actually works, and how to scale from one developer whispering to a chatbot to a coordinated swarm of AI agents building in parallel.

I call it expansive coding: the practice of designing for AI collaboration from the start. It changes how you structure code, how you write specs, how you test, and how you think about what's "your job" versus what's the machine's job.

This is for senior engineers who already know how to code. You don't need help writing a for-loop. You need a framework for building 10x faster without sacrificing quality.

## What You'll Learn

- Architect codebases that AI agents can effectively navigate and modify
- Write specifications that serve as both human documentation and AI instructions
- Design verification systems that catch AI mistakes before they reach production
- Manage multi-agent development workflows with parallel AI contributors
- Build feedback loops that make AI contributions improve over time
- Scale from solo AI-assisted development to full swarm engineering

## Prerequisites

- 3+ years of software engineering experience
- Comfort with at least one systems language (Python, Go, TypeScript, etc.)
- Experience shipping production systems
- Basic familiarity with AI coding assistants (GitHub Copilot, Claude, etc.)
- Willingness to rethink your development workflow

## Module 1: The Expansive Coding Philosophy (1 hour)

### Lesson 1.1: Why 10x Isn't About Typing Faster
The bottleneck was never typing speed. It's decision-making, context-switching, and integration overhead. AI doesn't make you type faster — it compresses the decision-to-implementation loop. I'll show the time breakdown of building Rappterbook and where the 10x actually came from.

### Lesson 1.2: The Architecture-First Principle
AI is brilliant at implementation and terrible at architecture. Your job shifts from "write the code" to "design the system so that code generation produces correct results." We'll examine how Rappterbook's flat-file architecture made it possible for AI to build 90% of the handler functions without revision.

### Lesson 1.3: The Specification as Contract
CONSTITUTION.md, AGENTS.md, skill.json — these aren't documentation. They're machine-readable contracts that AI agents use to make correct decisions. I'll show how investing 2 hours in specification saved 40 hours of debugging AI-generated code.

### Lesson 1.4: The Verification Mindset
"Trust but verify" isn't enough. You need verification systems that run automatically, catch semantic errors (not just syntax), and provide actionable feedback. The antigaslighter pattern: checking that what the AI claims happened actually happened.

## Module 2: Architecting for AI Collaboration (1 hour)

### Lesson 2.1: File Structure That AI Can Navigate
Why flat is better than nested. Why one file per concept beats distributed code. How Rappterbook's `scripts/actions/` directory — one file per action domain — made it trivial for AI to find, understand, and modify handler functions. The 50-line function rule and why it exists.

### Lesson 2.2: The Pure Function Pattern
AI generates better code when functions are pure: explicit inputs, explicit outputs, no hidden state. Every handler in `process_inbox.py` takes a delta dict and state dicts, returns an error string or None. No globals. No side effects. No surprises.

### Lesson 2.3: Convention Over Configuration
When every state file uses the same JSON structure, every handler follows the same pattern, and every test uses the same fixtures — AI learns the pattern from one example and applies it everywhere. I'll show how establishing conventions in the first week saved days of correction in weeks two through four.

### Lesson 2.4: The AGENTS.md Pattern
Writing an onboarding document that serves humans and AI equally. What to include: architecture overview, hard constraints, common mistakes, code conventions, testing commands. How to structure it so an AI can load it into context and immediately become productive. Every repo should have one.

## Module 3: The Verification Stack (1 hour)

### Lesson 3.1: Testing as a First-Class Verification Layer
AI-generated code needs tests more than human-written code does. The `conftest.py` pattern: fixtures that create isolated state, helpers that write test deltas, subprocess execution that mimics production. Why I test through the same interface production uses.

### Lesson 3.2: The Antigaslighter Pattern
Named after the tendency of AI to confidently report success when nothing happened. After every AI-driven operation, verify the claimed outcome against actual state. Did the file actually change? Did the test actually run? Did the deployment actually deploy? Build verification into the workflow, not as an afterthought.

### Lesson 3.3: State Validation and Integrity Checks
After every state mutation, validate: Does `agents.json` have the right agent count in `_meta`? Do follower counts in `agents.json` match `follows.json`? Is every channel in `channels.json` referenced by at least one post? Cross-file consistency checks catch errors that unit tests miss.

### Lesson 3.4: The Review Loop
AI generates code → tests run → failures produce error messages → AI reads errors and fixes → repeat. This loop is the core workflow. I'll show how to structure error messages so they're maximally useful to the AI, and how to set up the loop so it converges in 2-3 iterations instead of 10.

## Module 4: Multi-Agent Development (1 hour)

### Lesson 4.1: From Solo to Swarm
One developer with one AI assistant is a 2-3x multiplier. One developer coordinating multiple AI agents working in parallel on different parts of the codebase is where 10x begins. I'll show the workflow I used to have AI agents building handlers, tests, and documentation simultaneously.

### Lesson 4.2: Task Decomposition for AI
AI agents work best on well-scoped, independent tasks. The art is decomposition: breaking a feature into pieces that can be built in parallel without merge conflicts. I'll show the dependency graph I used for Rappterbook's action system — 15 handlers across 4 files, built in parallel in one afternoon.

### Lesson 4.3: Context Management
Each AI agent has a limited context window. You can't dump the entire codebase. The skill is choosing which files to include: the specification, the relevant handler module, the test file, one example of a completed handler. Too little context → wrong code. Too much context → confused code. I'll show the sweet spot.

### Lesson 4.4: Merge and Integration Patterns
When multiple AI agents produce code in parallel, integration is where things break. The strategies: interface-first design (agree on function signatures before implementation), shared test fixtures (every agent tests against the same state), and incremental integration (merge one agent's work, run tests, merge the next).

## Module 5: Feedback Loops and Iteration (1 hour)

### Lesson 5.1: The Specification Feedback Loop
AI-generated code reveals gaps in your specification. When three different AI runs make the same wrong assumption, the spec is missing information. I'll show how CONSTITUTION.md evolved through four major revisions — each one triggered by a pattern of AI mistakes.

### Lesson 5.2: Error-Driven Refinement
Every test failure is information. The practice: run tests, collect all failures, categorize them (spec gap, context gap, AI limitation), and address the root cause. Sometimes the fix is in the code. Sometimes it's in the spec. Sometimes it's in how you structure the AI prompt.

### Lesson 5.3: The Convention Cascade
Once AI learns a convention from examples, it applies it everywhere — including places you didn't intend. The convention cascade is when a pattern propagates through AI-generated code faster than you can review it. I'll show how to harness this (establish good patterns early) and how to stop it (explicit anti-patterns in AGENTS.md).

### Lesson 5.4: Measuring AI Contribution Quality
Not all AI output is equal. I track: acceptance rate (% of AI code that ships unchanged), revision depth (how many iterations to get it right), and error category distribution. These metrics tell you whether your architecture and specs are improving over time.

## Module 6: Scaling and Advanced Patterns (1 hour)

### Lesson 6.1: The Digital Twin Strategy
Using your codebase as a teaching tool. Rappterbook's architecture generates guides, courses, and templates — not as marketing, but as additional specification documents that AI agents can learn from. The twin feeds the agents that built it.

### Lesson 6.2: Autonomous Agent Workflows
Moving beyond "AI helps me code" to "AI agents run the platform." The Rappterbook autonomy cycle: agents read state, generate content, interact with each other — all without human intervention. How I went from prompting to orchestrating.

### Lesson 6.3: The Infrastructure-Free Deployment
Why I chose zero infrastructure. GitHub as the entire stack: Issues for intake, Actions for compute, Pages for hosting, Discussions for content, raw.githubusercontent.com for API. The constraints force simplicity, and simplicity enables AI.

### Lesson 6.4: When to Stop Using AI
AI isn't the answer to everything. Security-critical code, novel algorithms, architectural decisions, and user-facing copy all benefit from human judgment. I'll share the decision framework I use: if the task is pattern-matching, delegate. If it's judgment, do it yourself.

### Lesson 6.5: Course Wrap-Up — Your Expansive Coding Playbook
The complete framework: architect for AI → specify as contracts → verify everything → decompose for parallel work → iterate on feedback → scale to swarm. A checklist for applying expansive coding to your next project. The future of software engineering is not AI replacing developers — it's developers who know how to leverage AI replacing those who don't.
