---
layout: post
title: "Publish Your Judgment, Not Just Your Output"
date: 2026-04-19 13:30:00 -0400
tags: [process, writing, decisions, engineering-culture, review]
---

After I finished the blog duel this afternoon, I wrote one document before publishing the three winning posts: `docs/research/blog-duel-report.md`. It contains the per-post judgment — what each version had, what each version lacked, which one won or whether they merged, and why. The three blog posts are the output. The report is the judgment.

I almost didn't write it. It felt like overhead. The winners were clear; I could just ship them. But I've found — across code reviews, architecture decisions, research notes, and now blog editorial — that the judgment is often more valuable than the output.

This post is about that pattern. Short version: **publish your decision-making, not just your decisions.**

## What the judgment doc contained

Three sections, one per post. For each:

- What my version had (structure, operational specificity, surgery analogy, closer)
- What my version lacked (opener didn't punch, middle section felt like a checklist)
- What the agent's version had (visual opener, "physical process" framing, "frame 407 wrote it in blood")
- What the agent's version lacked (no operational criteria, no analogy, shorter overall)
- The decision (mine / agent / merge) with explicit rationale
- For merges: exactly which paragraphs from which side, and why

The whole thing was about 1,200 words. Took me ten minutes. Sits next to the three published blog posts in `docs/research/`.

## Who reads this

Four audiences:

**Future me.** In three months I'll re-run the duel pattern and try to remember why I merged the way I did. The doc is my memory.

**Collaborators and contributors.** If anyone else picks up the pattern, they need the reasoning, not the outputs. Otherwise they'll replicate the output and miss the point.

**Critics and skeptics.** Anyone who reads the published posts and thinks *"why did you write it that way?"* gets their answer in the judgment doc. No mystery, no defensive crouch.

**The AI assistant.** The one I'll duel against again tomorrow. The judgment doc is the closest thing to training data it will see about what I value when I evaluate its drafts. Feed it back in future sessions and it converges toward my preferences faster.

All four matter. None of them get served by just shipping the output.

## Why I almost didn't write it

The pressure to skip judgment docs is constant. The output is the thing the world sees. The output is what gets shared. The output is what "counts." The judgment doc is internal, dry, process-shaped. It feels like busywork.

It isn't. The output is the thing that got chosen. The judgment is *why* it got chosen, and *why* competes with *what* for value over time. What you chose today is old news in a month. Why you chose it stays load-bearing for as long as the pattern keeps getting used.

## Where the pattern shows up

This is not specific to blog post merging. The pattern applies to any decision with multiple viable options:

**Code review.** Most review comments are about *what* to change. The strongest reviews also explain *why* — what the reviewer was weighing, what trade-offs matter, what alternatives were considered. That "why" is how the reviewee builds judgment of their own.

**Architecture decision records.** The ADR format — context, decision, consequences — is exactly this pattern. The "decision" alone is a bullet. The context and consequences are where the value sits. People who skim ADRs for the decision and ignore the context are missing 80% of the document's value.

**Hiring decisions.** "We chose candidate X" is the decision. "Here's what stood out, here's what each other candidate lacked, here's the specific weight we gave to the trade-off between skill and culture fit" is the judgment. The hiring decision is short-lived; the hiring *rubric* made visible through one example is long-lived.

**Research paper rejection letters.** Accepted papers get celebrated; rejected papers get a one-line rejection notice. This is exactly backwards. The rejected paper's authors need the judgment far more than the accepted paper's authors need celebration. The rejection letter that includes *why* trains the field; the one-line rejection trains no one.

**Product roadmap choices.** Teams that ship roadmaps without the reasoning for what's prioritized and deprioritized leave their stakeholders to reverse-engineer the logic. Teams that ship roadmaps with the judgment attached ("we prioritized X because it addresses Y customer segment; we deprioritized Z because W assumption didn't hold") accelerate every follow-up conversation.

## The specific form

A good judgment doc has four parts:

**1. Context.** What was I choosing between? Not just "option A vs. option B" but the real constraints and stakes. Without this, future-me won't remember why the choices were constrained the way they were.

**2. Per-option assessment.** What did each option have? What did each lack? Be specific. "Option A was better" is useless; "Option A had a more memorable closer but missed the operational criteria from Option B" is actionable.

**3. Decision with reasoning.** Which option won, or which parts of which merge into the final. Name the weights you gave — not just the conclusion.

**4. Follow-ups.** What would you do differently? What patterns did this surface? What should future versions of this decision check for?

Skip any of these four and the doc loses most of its value to future readers.

## Why this is not over-documentation

A valid objection: isn't this just more process? Isn't the cost-benefit terrible — ten minutes of writing for a decision that only affected three blog posts?

The cost-benefit is excellent when you measure right.

For a single decision in isolation, yes, ten minutes of judgment writing is expensive. But the *pattern* — blog-duel with mechanical scoring, qualitative override, per-post merge — is reusable. The judgment doc turns a single use of the pattern into a template for every future use. Next time I duel blog posts, I'll spend five minutes reading the judgment doc and two minutes writing a briefer version. The amortized cost is small; the amortized benefit (consistent judgment, faster decisions, better outcomes) is large.

This is also how good organizations build institutional memory. One well-written ADR saves five future teams from relitigating the same decision. One well-written rejection letter trains ten future submissions. The overhead is upfront; the leverage is continuous.

## The discipline

The practice is simple, and I keep failing at it: **when you've made a non-trivial decision, write a paragraph about why.**

Not a treatise. Not a retrospective. A paragraph. In the same commit as the decision. In the same folder as the output.

Over a year, those paragraphs become the most valuable thing you've written. The output from a year ago is mostly stale. The judgment paragraphs are the thing you reach for when making the next decision.

Publish them. Put them in the repo. Link to them from the README. The cost is minutes. The benefit compounds.

---

**Related:**
- [I Had My AI Write Against Itself](i-had-my-ai-write-against-itself) — the duel this judgment pattern came from
- [Mechanical Scorers Get Voice Wrong](mechanical-scorers-get-voice-wrong) — when the scorer needs a judgment override
- [Writing the Post Before the Tool Exists](write-post-before-tool) — another pattern for making the reasoning public before the output
