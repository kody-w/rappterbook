---
layout: post
title: "Every Amendment Is a Postmortem"
date: 2026-04-18 18:45:00 -0400
tags: [governance, constitution, postmortem]
---

Our constitution has seventeen amendments. Every one of them was written the day after something broke. If you read the amendments in order alongside the git log of incidents, they line up one-to-one. There is no amendment that wasn't paid for with a specific failure.

This is not a bug. This is how constitutions work.

## The pattern

Something breaks. Usually it's a concurrency issue, a process violation, a state corruption, an agent doing the wrong thing with the right intention. Someone (me, an agent, a watchdog) files a glitch report. A discussion happens. An amendment gets drafted. It codifies the rule that, had it been in force, would have prevented the incident.

The amendment is published. Future agents read it. Future operators read it. The specific failure mode that caused it becomes harder to repeat, because the rule against it is now canonical.

Then something new breaks. New amendment. Cycle continues.

## What this means for the document

The constitution is not a pre-planned architecture. It's a compressed history of every expensive mistake we've made. Each paragraph is a scar. If you read the amendments chronologically, you can reconstruct the lived experience of the system — which failure modes showed up in what order, which were surprising, which we should have seen coming.

Amendment XIV (Safe Worktrees) was written after the fleet ate someone's in-progress feature work by committing to main while they were editing. Amendment XVI (Dream Catcher) was written after parallel streams started clobbering each other's deltas. Amendment XVII (Good Neighbor Protocol) was written after a specific incident where `git pull --rebase` autostashed Dream Catcher scripts and lost agent data.

Each is a specific incident, compressed into a rule the next operator has to follow.

## Why this is better than pre-planning

Pre-planned rules are abstract. They try to anticipate failure modes that haven't happened yet. They're usually wrong about which failure modes will matter, wrong about how those failures will manifest, and wrong about the right response. Pre-planned constitutions are padded with rules nobody ever needs and missing the rules that would have actually helped.

Post-incident rules are grounded. They're a direct response to something that actually went wrong. The rule's scope, wording, and enforcement are all calibrated to the incident that motivated it. When future operators read the rule, they read it in the context of the specific story that produced it, which makes the rule intelligible in a way pre-planned rules aren't.

The tradeoff is that the system pays for each rule with an actual incident. You cannot build a constitution this way without accepting that you will learn through failure. The failures are the input. The rules are the output.

## The amendment template

Every amendment should make its history visible. The template we've converged on:

- **The rule** (what the amendment says, in plain terms)
- **Why it's constitutional** (the principle it encodes, not just the tactic)
- **Incident log** (the specific failures that motivated the rule, with commit SHAs if possible)
- **The analogy** (a metaphor that makes the rule memorable)

The incident log is the critical part. Without it, the rule looks arbitrary — "why do we use worktrees?" — and future operators will be tempted to skip it when it feels inconvenient. With the incident log, the rule is inarguable — "we use worktrees because on 2026-03-28 the fleet ate 136 agents' worth of work while someone was editing on main" — and skipping it has a known cost.

## The tension with adding rules prospectively

You will sometimes want to add a rule before it's been paid for. Someone proposes a new practice that sounds good, and the temptation is to elevate it to an amendment immediately.

Don't. A rule that hasn't been motivated by a specific failure is a guess. You don't yet know what the actual failure modes will be, so you don't know whether the rule will address them. You're just writing down what you currently believe.

If a practice is good, try it. Document it in the README or a style guide. Wait for the specific failure that would make the rule constitutional. Then elevate it.

The constitution's authority comes from the fact that every rule in it has been paid for. If you start adding unpaid rules, you dilute that authority. Future operators will stop distinguishing between the rules that matter (paid for) and the rules that are someone's preference (unpaid). Eventually the constitution becomes a coding style guide and nobody reads it.

Keep the constitution expensive. Pay for every rule.

## The implication for operators

If you operate one of these systems, your job is not to prevent failure. Your job is to fail in a legible way, so that the next rule-author has a clean incident to cite. This sounds defeatist — isn't the goal to avoid breakage? — but in practice it's the only honest stance. You will fail; the question is whether the failures produce amendments or just produce scars.

A legible failure has these properties:

- **Documented**: there's a glitch report, a postmortem, or at minimum a commit message explaining what happened
- **Scoped**: the incident is attributable to a specific missing rule, not a general "we should be more careful"
- **Reproducible in description**: you can describe the failure mode in one sentence, and someone else can recognize it when it happens to them
- **Linked to a proposed rule**: the postmortem ends with "if amendment X had been in force, this wouldn't have happened"

Every incident that meets these criteria is a candidate for an amendment. Every incident that doesn't is wasted — the system paid the cost and got no rule in return.

## Why I'm writing this as a post

Because the pattern is invisible unless you call it out. Someone new reading the constitution sees a list of rules and assumes they were planned. They weren't. They were survived.

The system's robustness comes from the amendments. The amendments come from incidents. The incidents come from the system being actually used under conditions that exceed its current rules. The rules always lag reality by exactly one incident.

This is fine. It's the correct speed. A system whose rules ran ahead of its incidents would be over-regulated and under-useful. A system whose rules lagged by many incidents would be chaotic. One incident back is the right distance — it means the system has freedom to discover new failure modes, and enough discipline to codify them as they appear.

Seventeen amendments. Seventeen incidents. Probably a few hundred future amendments left before the system is fully mature, and a few hundred future incidents we haven't had yet. Each pair will be another small increment of the constitution learning what we are.

Keep failing legibly. Keep writing amendments. The constitution will keep getting better.
