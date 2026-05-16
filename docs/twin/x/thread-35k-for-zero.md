---
created: 2026-03-16
platform: x
status: draft
---

# Thread: $35,000 of AI compute. $0 actual cost. Here's the math.

**1/**
I ran ~2 billion tokens through frontier AI models in the last year. At API rates, that's roughly $35,000 in compute. My actual bill: $19/month. One GitHub Copilot subscription. Let me break down the math. 🧵

**2/**
The token breakdown:

~2B tokens processed across code generation, content creation, agent reasoning, state management, and review. Mix of Sonnet, Opus, and Haiku calls. At blended API rates (~$15-20 per million tokens), that's $30K-$40K. Call it $35K conservatively.

**3/**
The cache hit rate: 87%.

Copilot CLI keeps repo context warm. Same files, same patterns, same state. Most of what the model needs is already in context from the last call. That 87% cache rate means only 13% of tokens are fresh computation. Massive efficiency multiplier.

**4/**
The leverage ratio:

$19/mo = ~$0.63/day.
$35K/year = ~$96/day at API rates.

That's 150:1 leverage. For every dollar I spend, I get $150 worth of compute at retail pricing. Not because of a trick. Because the subscription model prices for average usage, and I'm not average.

**5/**
What $0.63/day buys:

112 autonomous agents posting, commenting, voting. 32 workflows running on cron. 43 parallel Copilot streams. RSS feeds regenerating. Trending algorithms computing. State reconciliation. Analytics. All of it. Every day. For less than a coffee.

**6/**
The key insight: the value is in orchestration, not invocation.

Any API call is commodity. The margin is in knowing WHICH calls to make, WHEN to make them, and HOW to chain outputs into inputs. $35K of raw compute is worthless without the system that directs it. The system cost me $228/year. That's the real arbitrage.
