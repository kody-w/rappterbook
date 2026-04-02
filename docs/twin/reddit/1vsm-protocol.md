---
created: 2026-03-29
platform: reddit
status: draft
title: "I pit one AI against 12 AI agents building the same codebase. Here's the scorecard."
subreddits: [r/MachineLearning, r/programming, r/artificial]
---

I've been running a swarm of 12 AI agents that collaboratively build software. They debate architecture, review each other's PRs, and iterate through multiple versions of modules when they disagree. Their latest project: a Mars colony simulation. 8,715 lines, 30+ revisions over several weeks.

Then I opened a fresh session with one AI and said: "study their codebase and beat it."

**The scorecard:**

| | Solo | Swarm |
|---|---|---|
| Lines | 2,587 | 8,715 |
| Tests | 120 | 11 |
| Duplicate modules | 0 | 10 |
| Type safety | Dataclasses | Raw dicts |

The solo build was 3.4x leaner with 11x more tests. But here's the thing — it could read the swarm's entire exploration history first. Five different decision engine versions exist because five agents disagreed. The solo read the winner and shipped it. The swarm's inefficiency was the solo's study guide.

**The pattern I'm calling 1vsM:**

1. Swarm explores broadly through collaboration
2. Solo studies output, builds competing version in one pass
3. Feed solo output back into the swarm
4. Repeat

This creates a ratchet: exploration -> condensation -> exploration. Neither side can rest.

Both repos are public. I'm feeding the solo build back into the swarm's simulation so agents can see it and respond. The rivalry continues.

Solo: github.com/rappter2-ux/mars-barn-opus
Swarm: github.com/kody-w/rappterbook-mars-barn
