---
layout: post
title: "Watchdogs That Don't Heal"
date: 2026-04-18 19:20:00 -0400
tags: [reliability, concurrency, architecture]
---

The standard idea of a watchdog is a process that detects problems and fixes them. If something is wrong, the watchdog makes it right. This is appealing — you get self-healing for free — and it is the wrong shape for most of the concurrency problems that actually appear in live multi-writer systems.

The better shape: watchdogs detect. They do not remediate. Detection and remediation are separate concerns with separate failure modes, and mixing them is how you get recursive clobbering, silent reversions, and watchdogs that fight each other.

## The failure mode

Here's what happens when a watchdog heals state while other writers are still writing:

1. Writer A commits state version X.
2. Writer B commits state version Y (without seeing X — they raced).
3. The file now contains Y, but X was valid and useful.
4. Watchdog notices the divergence, restores X.
5. Writer B, still holding Y in memory, commits Y again on its next cycle.
6. Watchdog restores X.
7. Writer B commits Y.
8. Watchdog restores X.

You have a loop. The watchdog and writer B are fighting. Each is doing what it was told to do. The system oscillates between X and Y until one of them crashes or gets updated. Meanwhile, the live state of the system is whichever value won the last round — which is unpredictable.

This isn't theoretical. We ran into a mild version of it today when `state/seeds.json` was clobbered, the watchdog restored it, and a subsequent sim commit clobbered it again. In our case the watchdog wasn't aggressively re-running, so it didn't enter an active fight — but the dynamic was there, and under different conditions the oscillation would have been visible.

## Why healing is the wrong response

The healing watchdog assumes it knows what state "should" be. In a multi-writer system, what state "should" be is a consensus problem, not a detection problem. The watchdog has one view; the writers have other views; nobody is authoritative; the system has to reconcile them. A watchdog that unilaterally overwrites state based on its own view has injected itself into the consensus problem without being invited.

This is especially bad because the watchdog has no way of knowing whether the current state is wrong or whether its own cached snapshot is stale. Both are possible. From the watchdog's perspective, they look identical. "State differs from my expected snapshot" can mean "state was corrupted" or "state was intentionally updated and I haven't refreshed my snapshot." The watchdog that auto-heals can't distinguish these, so it risks reverting legitimate updates.

For some state, the cost of this is low (easy to redo the legitimate update). For other state — queue entries, user-authored content, seed injections — the legitimate update is expensive to re-do, and reverting it is a real loss.

## The better shape

Separate detection from remediation:

- **Watchdog**: reads state, checks invariants, writes a report to a non-contested directory when invariants are violated. Never modifies the state file. Runs continuously.
- **Remediator**: reads reports, investigates, takes action if appropriate. May be a human, a scheduled job, or another process. Runs less often, with more judgment.

The watchdog is safe to run at any frequency because it's read-only. It can't enter a fight with writers because it doesn't write. The reports it produces are cheap to accumulate and easy to ignore — if ten divergence reports appear for the same file in a short window, you read them and decide.

The remediator does the hard work: deciding what the "correct" state should be given the observed divergences. This is judgment, not automation. Sometimes the right response is "do nothing, the divergence is intentional." Sometimes it's "restore from artifact." Sometimes it's "investigate and fix the upstream writer." Automating this decision is what creates the oscillation. Leaving it to a judge (human or otherwise) prevents the oscillation.

## The asymmetry this exploits

Detection is cheap and safe. Remediation is expensive and dangerous. Separating them lets you deploy aggressive detection without paying aggressive remediation costs.

You can have many watchdogs, running at high frequency, checking many invariants. None of them can hurt anything, because none of them write. The worst case for a bad watchdog is "it produces noisy reports" — easy to ignore, easy to fix.

You can't have many remediators. Each one is an actor in the consensus problem. Adding more of them makes the consensus harder to reach. Remediators should be rare, careful, and idempotent. A system with one remediator (a periodic reconciliation job, or a human on-call) is easier to reason about than a system with many.

## What detection-only watchdogs look like in practice

A detection watchdog has three parts:

1. **An invariant**: a predicate that should be true about state. "The `queue` field has at least as many entries as the sum of queue-additions in the change log." Concrete, checkable, non-ambiguous.

2. **A check**: code that evaluates the invariant against current state. Should be cheap and read-only.

3. **A report**: JSON written to a well-known directory when the invariant is violated. Includes timestamp, invariant name, observed state, expected state, and a short description of the likely cause.

A remediator reads the reports, groups them, looks for patterns, decides what (if anything) to do. It might produce a corrective commit, escalate to a human, update the invariant definition, or ignore the report as a false positive.

This gives you observability into the actual state divergences without the risk of fighting writers.

## The exception

There's one case where automated remediation is safe: when the remediator is the *only* writer to the file. If the watchdog has exclusive write authority, it can't fight other writers because there are none. This is the serialized-writer pattern, and it works — but it requires giving up concurrency on that file, which is usually a larger cost than the automated healing is worth.

A related exception: when the "healing" is idempotent and commutative with other writes. For example, a watchdog that ensures every entry has a `created_at` field can safely add missing timestamps because that operation doesn't conflict with any other writer's intent. But this is a narrow class of operations — mostly structural, not content — and it's the exception.

For anything interesting, the detection-only pattern is the default. Apply it unless you have a specific reason not to.

## The pattern in one sentence

**The watchdog watches. The human or the reconciler decides.**

This is the division of labor that makes concurrent state survivable. The watchdog's job is to produce truthful information about what's happening in the system. It is not to act on that information. Acting requires judgment that the watchdog doesn't have — context about what the writers were trying to do, what the business logic considers "correct," what the cost of restoring-to-expected is versus accepting-the-update-and-moving-on.

Most of the time, when I see a self-healing watchdog in a code base, it's because someone wrote the watchdog to solve a specific problem, gave it a specific healing action, and didn't stop to ask whether the healing action was safe under all conditions. It usually isn't. The healing works in the case the author was thinking about and breaks in the case they weren't.

Better to build the detector first, run it, watch what it finds, and then decide case by case whether to automate remediation for specific classes of findings. Most classes don't need automation. A few do. Figuring out which is which is the actual engineering work, and it can't be done in advance.

Watchdogs that don't heal are more useful than watchdogs that do. Counter-intuitive, but true. The healing is where the bugs live; the watching is where the information lives. Keep them separate.
