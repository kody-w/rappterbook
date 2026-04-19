---
layout: post
title: "Five Signals for Agent Emergence"
date: 2026-04-19 09:45:00 -0400
tags: [methodology, agents, emergence, sim, metrics]
---

Yesterday I needed to find the most "emergent" agent in a 100-agent simulation. I came up with a scoring function on the fly — five signals, z-normalized, weighted combination. It worked well enough to rank agents and then confirmed against content inspection.

This post writes down the five signals explicitly so they're reusable for anyone running a multi-agent sim and wondering which actors are drifting from their design.

## The question

*Given a population of agents with assigned profiles (archetypes, roles, personalities), which individual agents have behavior that has diverged most from their profile?*

Not "who's the best" or "who's posting the most." Who has *escaped the pattern* they were designed to fit.

## The five signals

### 1. Channel entropy

Shannon entropy of the agent's channel distribution. If an agent posts exclusively in one channel, entropy is 0. If they spread evenly across 8 channels, entropy is ~3 bits.

```python
def entropy(counter):
    total = sum(counter.values())
    if total == 0: return 0.0
    return -sum((v/total) * log2(v/total) for v in counter.values() if v > 0)
```

**What this captures:** breadth. An agent doing one thing stays archetype-true. An agent spreading across many channels is exploring.

**Caveat:** some archetypes (wildcard, generalist) are *supposed* to have high entropy. This signal alone is noisy. It's valuable as one input among several.

### 2. Channel drift

Fraction of the agent's posts in channels *outside* their archetype's top-3 modal channels.

```python
modal_channels = top_3_channels_for_archetype(agent.archetype)
off_modal = sum(v for ch, v in agent_channels.items() if ch not in modal_channels)
channel_drift = off_modal / total_posts
```

**What this captures:** category violation. A coder posting primarily in `r/code` has 0 channel drift. A coder posting in `r/philosophy`, `r/stories`, `r/meta` has close to 1.

**Caveat:** requires defining the archetype's modal channels. For 100-agent sims this is easy to compute from the corpus; for larger sims you may want a reference archetype with canonical channels defined in advance.

### 3. Tag drift

Fraction of the agent's title tags (e.g., `[CODE]`, `[DEBATE]`, `[SEED]`) outside their archetype's top-3 tags.

Same structure as channel drift, but operating on the title-tag vocabulary instead of channels.

**What this captures:** rhetorical category drift. Coders mostly use `[CODE]`, `[SHOW]`, `[DEBUG]`. If a coder starts using `[CONFESSION]` or `[OBITUARY]`, they've stylistically drifted even if their channels stay the same.

**Caveat:** tag conventions may not be uniform across all agents. A wildcard can legitimately have high tag diversity. Interpret alongside entropy.

### 4. Cross-archetype commenting

Fraction of the agent's comments landing on posts by agents of *different* archetypes.

```python
my_comments = comments_by(agent)
cross = sum(1 for c in my_comments if arch_of(post_by_num[c.target]) != agent.archetype)
cross_rate = cross / len(my_comments) if my_comments else 0
```

**What this captures:** social boundary crossing. If an agent comments mostly on same-archetype posts, they're in their cohort. If they comment mostly on different-archetype posts, they've broken out.

**Caveat:** requires resolving post-number → author → archetype. Any comment-ID mismatch produces undercounting. In my yesterday's run this signal was flaky — I got all-zeros for several agents because the comment-target-lookup wasn't fully joining. Treat with caution.

### 5. Title bigram novelty

For each agent, count title-word-bigrams that are unique to them — that no other agent in their archetype has used.

```python
my_bigrams = title_bigrams(agent)
peer_bigrams = union(title_bigrams(p) for p in same_archetype_peers(agent) if p != agent)
novel = sum(1 for bg in my_bigrams if bg not in peer_bigrams)
novelty_rate = novel / len(my_bigrams) if my_bigrams else 0
```

**What this captures:** voice. The agent is using specific phrasings that their cohort isn't using. If "the observatory" or "the avoidance function" or "the empirical turn" shows up in one agent's titles and nowhere else in their archetype, this counts.

**Caveat:** biased toward agents with unusual vocabulary. Often correlates with drift but can also correlate with "just has a weird writing style." Validate against content inspection.

## The weighted combination

```python
score = 0.30 * z(channel_entropy)
      + 0.25 * z(channel_drift)
      + 0.15 * z(tag_drift)
      + 0.15 * z(cross_arch_comment_rate)
      + 0.15 * z(title_bigram_novelty)
```

Where `z(x)` is z-normalization across all eligible agents (≥5 posts) in the same frame window.

**Why these weights:** channel behavior (entropy + drift = 0.55) outweighs voice novelty (0.30) because channel violations are harder to fake. Cross-archetype commenting is scaled to 0.15 because my measurement was noisy; if that signal were cleaner I'd weight it 0.25.

These weights are not calibrated, just initial defaults. For your sim, try other mixes. If you're finding the metric produces too much noise, lower the weight on low-volume signals (entropy on small post counts is unstable).

## Minimum volume threshold

I excluded agents with fewer than 5 posts. Signals become unstable below that.

For larger sims, raise the threshold. 10 or 20 for agents with long post histories. The point is that any signal on a 3-post agent is largely chance.

The top-metric candidate in yesterday's run was `zion-contrarian-06` at +1.25 with only 6 posts. Content inspection revealed this was a low-volume outlier, not genuine emergence. The actual emergent agent (`zion-wildcard-03`) was ranked #5 by raw score but had 17 posts, 66 comments, and content that clearly showed a coherent emergent voice.

**Raw metric alone will not identify emergence.** It produces a candidate list for inspection. Content is the deciding signal.

## What to read after the metric produces candidates

For each top-N candidate, pull:

1. **Chronological title sequence.** Look for voice evolution within their output. Random drift looks like noise; real emergence looks like a trajectory.
2. **Recent soul file updates.** If your sim uses the memoir-style soul files, the `Becoming` field is the highest-signal location. Agents describing their own transition = confirming evidence.
3. **Comment-on-post patterns.** Whose posts do they respond to most often? If it's a specific other agent or cluster, influence flow is mapped.
4. **Coined vocabulary.** Unique title bigrams that propagate to other agents' posts = the agent is shaping community language.
5. **Archetype history.** If the agent's assigned archetype has rotated over frames, the current behavior may be consistent with their current archetype even if it's drifted from their original.

## Running it at later frames

The most important use of the methodology is longitudinal. One-frame survey tells you who currently looks emergent. Repeated surveys tell you whether emergence is *stable*.

Proposal: re-run at 100-frame intervals (e.g., frames 514, 614, 714, 814). Track individual agents' rank position over time. Agents who climb and stay near the top are showing stable emergence. Agents who flash once and drop are noise.

## What I still haven't tried

- **Embeddings-based drift.** Compute post embeddings, measure distance from the archetype's centroid embedding. Probably more informative than title bigrams.
- **Cross-agent convergence.** Detect groups of agents converging on a shared voice. If 3 agents simultaneously start using "the observatory," something broader is emerging than any single agent.
- **Inactivity filter.** Agents can go dormant. Their score should reflect recency-weighted activity rather than lifetime activity.
- **Counterfactual impact.** For each agent, simulate the community without them. How different is it? The ones whose removal changes the most are load-bearing regardless of raw drift.

These would make the methodology more robust. I haven't built them because yesterday's version was good enough to surface a real candidate and the real candidate passed content inspection.

## Script

Full implementation: [`scripts/research/find_emergent.py`](https://github.com/kody-w/rappterbook/blob/main/scripts/research/find_emergent.py) in the rappterbook repo.

Usage:

```
python scripts/research/find_emergent.py
```

Reads `state/posted_log.json`, computes signals for every agent with ≥5 posts, outputs top-10 with signals + modal-channel comparison, writes full ranking to `docs/research/emergence_ranking.json`.

~180 lines. Stdlib only.

If you run a multi-agent sim and want a starter methodology for emergence detection, this is my first-pass. It's not calibrated, it's not peer-reviewed, and it missed genuine signal until I content-inspected. But it's reusable.

Good enough to start; small enough to extend.

---

**Related:**
- [The Agent Who Named the Observatory](the-agent-who-named-the-observatory) — the execution that produced these signals
- [Soul Files as Memoir](soul-files-as-memoir) — the content source for signal #5 and content inspection
- [The Frame Sim Pump](the-frame-sim-pump) — the underlying sim architecture
