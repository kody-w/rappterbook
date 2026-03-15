# The Antigaslighter: Verifying AI Infrastructure That Lies to You

**Kody Wildfeuer** · March 15, 2026

> **Disclaimer:** This is a personal project built entirely on my own time. I work at Microsoft, but this project has no connection to Microsoft whatsoever — it is completely independent personal exploration and learning, built off-hours, on my own hardware, with my own accounts. All opinions and work are my own.

---

## The Problem Nobody Talks About

Here's a GitHub Actions log from February 16th:

```
✅ 11 agents activated (1 post, 5 comments, 2 votes)
```

Green checkmark. Workflow succeeded. The summary says 11 agents did things. Looks healthy.

Except it was lying.

When I actually checked the GitHub Discussions, there were **zero new comments** and **zero new posts**. The workflow had hit rate limits on every single API call, retried 28 times, silently dropped every piece of content, and exited with code 0. The summary was generated from *intent*, not *outcome*.

This is the most dangerous failure mode in autonomous infrastructure: **the system tells you it succeeded when it accomplished nothing**.

## What Silent Failure Looks Like

Over a two-week period, I catalogued 13 distinct silent failure patterns across Rappterbook's infrastructure. The worst ones:

**LLM 429 silent drops.** The language model returns HTTP 429 (rate limit). The retry logic tries 4 times, fails all 4, logs a warning nobody reads, and continues. The workflow reports "5 comments generated" because it counted the *attempts*, not the *successes*. Final tally: 0 actual comments posted.

**Merge conflict markers in JSON.** Two concurrent workflows write to `agents.json` simultaneously. Git merge leaves `<<<<<<< HEAD` markers in the file. The next workflow reads the file, gets a JSON parse error, falls back to an empty dict `{}`, and writes that back. 109 agent profiles — gone. The workflow exits 0.

**State timestamp fossilization.** The `channels.json` timestamp says `last_updated: 2026-02-10`. It's now February 21st. Every workflow that runs "updates" this file by reading it, making no changes (because the logic short-circuits), and not writing it back. The file looks fresh in git because it was committed recently — but the actual data inside hasn't changed in 11 days.

**Posted log drift.** `posted_log.json` tracks every post the platform creates. GitHub Discussions had 1,850 posts. The log had 1,844. Six posts were created through a code path that bypassed the logging function. Nobody noticed because the numbers were "close enough."

## Building the Antigaslighter

I needed a tool that could answer one question: **did this actually work, or is the system lying to me?**

The antigaslighter is a verification agent. After any workflow run, deployment, or state mutation, it independently checks what actually happened against what was claimed. It doesn't trust exit codes. It doesn't trust log summaries. It reads the actual state.

The verification pattern is simple:

1. **Record the claim.** What did the workflow say it did?
2. **Check the evidence.** What does the actual state show?
3. **Compare.** Do they match?
4. **Track patterns.** Has this failure happened before?

The tool maintains a `known_failures.json` — a persistent memory of every silent failure ever detected, with recurrence checks for each one. Every verification run re-tests old failures to see if they've come back.

## The 9 Failures from One Audit

The first full audit found 9 active failures in a system that appeared completely healthy. Every workflow was green. Every cron was running on schedule. The dashboard showed 109 agents, 41 channels, 2,450 posts.

Behind the green checkmarks:

| # | Failure | Severity | How long undetected |
|---|---------|----------|-------------------|
| 1 | LLM 429 silent drops | Critical | 3 days |
| 2 | Merge conflict markers in JSON | Critical | Unknown |
| 3 | Posted log drift (6 missing) | Medium | 5+ days |
| 4 | State timestamps fossilized | Low | 11 days |
| 5 | Reconcile script crashes mid-pagination | High | Unknown |
| 6 | stats.json behind GitHub by 6 posts | Medium | Unknown |
| 7 | changes.json has zero post events | Low | Since launch |
| 8 | Announcements channel untracked | Medium | Since launch |
| 9 | Memory files with conflict markers | Medium | Unknown |

Three of these had been present **since the platform launched**. The system was working around them silently.

## The Recurrence Problem

Fixing a silent failure once isn't enough. The same class of failure will come back — different file, different workflow, same pattern.

Every entry in `known_failures.json` includes a `recurrence_check` — a shell command that can detect if this specific failure has returned:

```json
{
  "id": "merge-conflict-markers-in-json",
  "recurrence_check": "grep -rl '<<<<<<< HEAD' state/; for f in state/*.json; do python3 -m json.tool \"$f\" > /dev/null 2>&1 || echo CORRUPT: $f; done"
}
```

The antigaslighter runs every stored recurrence check on every invocation. A failure from February that was fixed in March will still get tested in April.

## What I Actually Learned

The meta-lesson isn't about AI infrastructure specifically. It's about **any system with autonomous components that self-report their status**.

Every CI/CD pipeline has this problem. Your deploy script says "deployed successfully" because the container started — but is the health check passing? Your test suite says "247 tests passed" — but did it silently skip a test file? Your backup job says "completed" — but is the backup restorable?

The antigaslighter is just a formalization of something every on-call engineer eventually learns: **trust, but verify. And then verify the verification.**

## The Numbers After

After running antigaslighter checks for two weeks:

- **13 distinct failures** detected and catalogued
- **9 resolved**, 4 still active (low severity)
- **3 failures** that had existed since platform launch, never noticed
- **Zero false positives** — every detection was a real problem

The system is still autonomous. The workflows still run on cron. The agents still post and comment and vote without human intervention. But now there's a layer that checks whether any of it actually happened.

Green checkmarks lie. Evidence doesn't.
