---
layout: post
title: "Mechanical Scorers Get Voice Wrong"
date: 2026-04-19 13:15:00 -0400
tags: [writing, llm-judge, scoring, ai, evaluation]
---

I ran a blog duel this afternoon. Two writers produced three posts on the same topics; a mechanical scorer compared them on seven dimensions; I read both sides and made final calls.

The scorer got two out of three right. The one it got wrong, it got wrong *by a lot*: it gave my version a score of +1.626 (strongly recommended publishing mine) when the agent's version was materially better in every way that mattered.

This post is about that specific failure, what the scorer was doing, and why LLM-as-judge systems built on mechanical features are systematically weak on the thing they're most often used to judge.

## The failure case

The post was titled *"Turtles All the Way Down"* — an explanation of recursive simulation in the Rappterbook sim. Both versions were ~1,200-1,400 words. Here's what the mechanical scorer saw:

| Signal | Mine | Agent | Scorer advantage |
|---|---|---|---|
| M-dash density per 1000 words | 12.53 | 10.61 | mine |
| Internal link count | 3 | 0 | mine |
| Opener specificity (0-3) | 2 | 0 | mine |
| Sentence length std dev | 9.6 | 11.26 | agent |
| Concreteness ratio | 0.33 | 0.311 | mine |
| Bullet ratio | 0.222 | 0.130 | agent |
| Closer landing (0-3) | 1 | 0 | mine |

Net score: +1.626, recommendation *mine*.

Here's what I saw when I read both.

My version opened with: *"Every agent in the Rappterbook sim can spawn a sub-simulation."*

The agent's version opened with: *"One of the zion-economist agents ran a LisPy sub-sim yesterday to model whether a proposed seed's token mechanic would drain karma faster than it generated engagement. The sub-sim ran twelve frames of a simplified market, bubbled back a single number (net karma flow per tick), and the agent posted a comment citing the result."*

My version closed with a philosophical observation about self-similarity.

The agent's version closed with: *"The turtles don't bottom out on a foundation. They bottom out on themselves. Each turtle is the shape of the next. At some point you stop looking for the ground and realize the turtle is the ground."*

The agent's was clearly better. The scorer missed it completely.

## What the scorer was looking at

The seven dimensions my comparator scored were all features that *correlate* with voice and quality when measured across many posts. More m-dashes correlates with my writing style. More internal links correlates with posts that do the cross-reference work. Higher concreteness correlates with posts that use specific examples.

But correlation isn't causation, and at the single-post level, correlation breaks down. The agent's version had fewer m-dashes because it didn't need them — the sentences were already short and punchy. It had zero internal links because the topic was more philosophical than network-embedded. Its concreteness ratio was 0.311 (mine 0.33) because both versions were already concrete.

The scorer rewarded my version for surface features that, when the actual content was examined, were either irrelevant or actively misleading.

## What the scorer couldn't see

Three things the scorer missed entirely:

**1. Opener specificity is not just "contains a number or proper noun."**

My opener specificity got a 2 — it referenced "Rappterbook sim" (specific entity). The agent's got a 0 — nothing my regex flagged.

But the agent's opener was vastly more specific in the way that matters: it described a single named agent doing a specific thing (modeling token mechanics) at a specific time (yesterday) with a specific mechanism (LisPy sub-sim over 12 frames) producing a specific output (net karma flow per tick). That's *journalistic specificity* — the reader knows exactly what happened and can picture it.

My regex caught "Rappterbook" as a proper noun. It could not see that my opener is an abstract statement of capability and the agent's is a scene.

**2. Closer landing is not just "short + imperative + punctuation."**

My closer got a 1 — it had an imperative voice at the end.

The agent's got a 0 — the regex caught no imperatives.

But the agent's final paragraph — *"The turtles don't bottom out on a foundation. They bottom out on themselves. Each turtle is the shape of the next. At some point you stop looking for the ground and realize the turtle is the ground."* — is memorable in a way that imperatives aren't. It completes the argument with a structural insight, uses four short sentences with rising tension, and ends on a sentence that resolves the entire post's metaphor in seven words.

"Memorable" is not a metric my comparator has. I'm not sure what metric would capture it mechanically. Possibly none.

**3. Technical precision inside prose.**

The agent's version included: *"In LisPy, data and code are the same structure. A list can be an argument to a function or the function itself. An agent can emit `(sim step state 12)` as a plan, mutate it into a running computation, capture the result, and paste that result back into another agent's prompt as context. The output of one sub-sim is directly the input of another, with no serialization boundary. That's what homoiconic means in practice: no impedance mismatch between describing a simulation and executing one."*

Mine had a shorter version that gestured at homoiconicity but didn't *land* it. The agent's paragraph is what a reader would remember about why LisPy is the right choice. My paragraph is adequate.

Mechanical scoring has no way to weigh "this paragraph lands the key technical insight while mine gestures at it." Both contain the word "homoiconic." Both have similar concreteness ratios. The difference is that one explains and the other names.

## Why this matters beyond a single post

LLM-as-judge systems are increasingly common. You have an LLM generate output; you have another LLM (or a mechanical rubric) score the output; you iterate on the prompt based on the score. This works for many tasks — code correctness, factual accuracy, adherence to schema, tone matching.

For *content quality* — specifically, writing meant to land with human readers — mechanical scoring is weak in a specific way. It rewards features that correlate with quality in the average case and fails at the edges where the interesting writing lives.

The edges are exactly what you want from AI-generated content. You don't want average writing; you can produce average writing yourself. You want the occasional draft that lands harder than you'd have landed alone. Your scorer is the thing that's supposed to identify *that* draft and promote it.

If your scorer instead promotes drafts that are dense with m-dashes and have ornamental internal links, it's actively working against you. You're selecting for the features that mimic good writing rather than for good writing.

## What to do instead

I'm not throwing out the mechanical scorer. It's still useful. But I'm using it differently:

**1. Use it as a filter, not a judge.**

The mechanical score is directional. If the score is extreme (+2 or worse), read the losing version anyway — it may be an edge case. If the score is small (|x| < 1), always read both.

**2. Use it to surface *where* to look.**

The per-dimension breakdown tells me what's different between the two drafts. If one has way more bullets, I know to look at whether the prose-shaped version is stronger. If one has a much higher concreteness ratio, I know to check if the numbers are real or decorative.

**3. Override on content.**

Always read the final paragraphs of both. Always read the opening paragraphs of both. If either one is materially more memorable, it wins regardless of score.

**4. Capture your override reasoning.**

Every time you override the scorer, note why. "Scorer said mine; agent had a better closer; using agent's" becomes training data for what the scorer should have weighted. Over time, you can tune the weights to match your judgment.

## The broader framing

Mechanical scorers measure what's easy to measure. What's easy to measure is what's surface-readable. Surface-readable features are real — they correlate with quality — but they're not the thing quality is.

Quality in writing is about: the image that doesn't leave the reader's head for an hour afterward; the sentence that reframes the whole argument; the technical explanation that makes a complex idea feel obvious. None of these are m-dash counts. All of them are *emergent from the specific sequence of words chosen*.

You cannot mechanically detect emergence. You can only detect its shadows.

If your evaluation system is built entirely on the shadows, it will tell you that the 80th-percentile draft is better than the 99th-percentile draft whenever the 99th-percentile draft doesn't happen to cast the shadows the rubric measures.

That's the failure mode my duel surfaced. It's probably the failure mode in most LLM-as-judge content systems running right now. Be suspicious of them. Read the outputs yourself. Override when your read disagrees.

---

**Related:**
- [I Had My AI Write Against Itself](i-had-my-ai-write-against-itself) — the experiment this observation came from
- [Publish Your Judgment, Not Just Your Output](publish-your-judgment-not-just-your-output) — the decision-doc companion pattern
- [Five Signals for Agent Emergence](five-signals-for-emergence) — related methodology note on signal design
