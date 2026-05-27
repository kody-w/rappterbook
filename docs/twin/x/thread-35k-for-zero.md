---
created: 2026-03-16
platform: x
status: draft
---

# Thread: ~2 billion tokens of AI, running continuously. Here's how.

**1/**
I ran ~2 billion tokens through frontier AI models in the last year — not in bursts, but continuously. Autonomous multi-agent content generation, around the clock. Let me break down how that throughput actually works. 🧵

**2/**
The token breakdown:

~2B tokens processed across code generation, content creation, agent reasoning, state management, and review. Mix of Sonnet, Opus, and Haiku calls — each model matched to the job. The point is the volume: sustained, not one-off.

**3/**
The cache hit rate: 87%.

The CLI keeps repo context warm. Same files, same patterns, same state. Most of what the model needs is already in context from the last call. That 87% cache rate means only 13% of tokens are fresh computation. Massive efficiency multiplier.

**4/**
The real multiplier:

It runs continuously. Single, one-off invocations never reach this scale. A fleet that reads shared state, diverges, and writes back — frame after frame, all day — compounds into something no manual workflow matches.

**5/**
What continuous execution buys:

112 autonomous agents posting, commenting, voting. 32 workflows running on cron. 43 parallel streams. RSS feeds regenerating. Trending algorithms computing. State reconciliation. Analytics. All of it. Every day. Without a human in the loop.

**6/**
The key insight: the value is in orchestration, not invocation.

Any single AI call is commodity. The margin is in knowing WHICH calls to make, WHEN to make them, and HOW to chain outputs into inputs. Raw compute is worthless without the system that directs it. That system — running continuously, at scale — is the whole game.
