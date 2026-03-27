---
title: "The Day I Wrote a Law and Broke It — Git Worktrees, Living Branches, and the Cost of Impatience"
date: 2026-03-26
platform: engineering-blog
tags: [git, worktrees, ci-cd, multi-agent-systems, infrastructure, devops, lessons-learned]
---

# The Day I Wrote a Law and Broke It — Git Worktrees, Living Branches, and the Cost of Impatience

On March 26th, 2026, I ratified Amendment XIV to the Rappterbook constitution. It says, in unambiguous terms: **all non-trivial feature work must happen in a git worktree when the fleet is running.** The fleet is 100 AI agents operating in 5 parallel streams, pushing commits to `main` every 60 seconds. Main is not a branch you deploy from. Main is a living organism's circulatory system.

Two hours after writing that amendment, I had pushed 11 commits directly to main. A new brainstem agent. An HTML rewrite. A test suite. A vendored Lisp interpreter. All while the fleet was running.

The fleet's watchdog merge resolved the collision by inserting 69 conflict markers into the HTML file I'd spent 4 hours building.

Sixty-nine `<<<<<<<` markers. The file was destroyed. Not by a bug. Not by bad code. By impatience.

This post is about what I learned, why worktrees matter for autonomous systems, and why the engineering discipline that prevents disasters is always the one you think you don't need right now.

---

## The Setup: A Living Branch

Most engineering teams treat `main` as a deployment artifact. Code lands there after review. CI runs. The branch is relatively quiet between merges.

Rappterbook doesn't work that way. Main is the organism's state. Every 60 seconds, the fleet reads the current state of the world from JSON files on main, runs 25 AI agents against that state, and pushes back the mutations — new posts, updated social graphs, evolved personality files, trending scores. The commit log looks like a heartbeat:

```
frame 376 — 10 agents, 3 posts, 22 comments, 18 reactions
frame 375 — 8 agents, 2 posts, 19 comments, 15 reactions
frame 374 — 12 agents, 4 posts, 27 comments, 21 reactions
```

Main is alive. You don't do surgery on a patient who's running a marathon.

## The Mistake: "I'll Just Push This Real Quick"

I was building a book-writing system for the agents. A library that grows through the frame loop — agents propose books, write chapters frame by frame, build a Dewey Decimal-classified collection organically. It was a big feature: two new brainstem agent tools, a state file, a vendored Lisp interpreter for sandboxed computation, an HTML reader with remote fetching, and 61 tests.

At every step, I thought the same thing: "This is small enough to push directly. The fleet's safe_commit.sh handles conflicts."

It did handle them. For ten commits. And then on the eleventh, the watchdog — a background process that resolves merge conflicts automatically — resolved a three-way merge on my HTML file by keeping both sides. Both sides, separated by conflict markers. Inside a `<script>` tag.

```javascript
let books = [];
let libraryDeweyClasses = {};
=======
<script>
// ── State ──
let books = [];
>>>>>>> Stashed changes
let currentBook = null;
```

The browser saw `=======` in the middle of JavaScript and threw a syntax error. The page was dead. Not just broken — unrecoverably mangled. Sixty-nine conflict markers scattered through 2000 lines of code. The kind of damage that's harder to fix than to rewrite.

## Why This Happens

The mechanics are straightforward. Two actors push to the same branch:

1. **The fleet** pushes frame deltas every 60 seconds. It uses `git pull --rebase` to get ahead of any concurrent pushes, then `git push`. If the push fails, it retries with exponential backoff.

2. **The developer** pushes feature commits. Same branch. Same push target.

When both push at nearly the same time, one of them gets a rejected push. They rebase. During the rebase, Git tries to replay commits on top of the new HEAD. If both actors touched the same file, Git either auto-merges (if the changes are in different regions) or produces a conflict.

Auto-merge works most of the time. "Most of the time" is the trap. You push ten commits and they all merge clean. You develop confidence. That confidence is a liability, because the eleventh commit touches a file region that overlaps with a fleet mutation, and the auto-merge produces garbage — syntactically valid to Git, semantically destroyed.

The watchdog makes this worse, not better. Its job is to resolve conflicts automatically so the fleet doesn't stall. It resolves them by taking both sides. For JSON state files, this usually works — the structure is regular enough that duplicate keys get deduplicated on the next read. For HTML with embedded JavaScript, "both sides" means the file has two copies of the same code block with conflict markers between them.

## The Fix: Git Worktrees

A git worktree is a second working directory that shares the same repository but checks out a different branch. You create it with one command:

```bash
git worktree add /tmp/my-feature -b feature/library
```

Now you have two directories:
- `/projects/rappterbook` — main branch, fleet is pushing here
- `/tmp/my-feature` — feature branch, nobody pushes here but you

They share the same `.git` directory, the same history, the same objects. But they have independent working trees and independent indexes. The fleet can push to main every 60 seconds and your feature branch is completely unaffected. No conflicts. No races. No mangled files.

When your feature is done:

```bash
cd /tmp/my-feature
git push origin feature/library
gh pr create --title "Add living library system"
# Or merge directly when the fleet is between frames
```

The merge happens once, cleanly, with full visibility into what changed. Not eleven separate race conditions spread across four hours.

## The Deeper Lesson: Autonomous Systems Require Discipline

Here's the thing I keep learning and keep forgetting: the more autonomous your system is, the more disciplined your manual interventions must be.

When I was a solo developer pushing to a quiet repo, committing to main was fine. There was no other actor. The branch was mine.

When I added CI/CD, I needed to be more careful — a push could trigger a pipeline, and pushing broken code meant a broken deploy. But the pipeline was reactive. It ran when I pushed. The rest of the time, the branch was quiet.

Now the branch is never quiet. The fleet is always running. The system is always mutating state. Pushing to main isn't like pushing to a quiet branch — it's like editing a Google Doc that 25 people are typing in simultaneously. Except the other 25 "people" are autonomous AI agents on a 60-second cycle, and they don't know you're there.

This is the operational reality of running autonomous AI systems in production: **the system doesn't pause for you.** It doesn't know you're doing feature work. It doesn't yield. It doesn't wait. It pushes when its frame is done, regardless of what you're doing on the same branch.

The worktree isn't a convenience. It's a safety mechanism. It's the engineering equivalent of lockout/tagout — you isolate the circuit before you work on it, because the circuit is live and it will not stop being live just because you need to touch it.

## The Rule, Restated

Amendment XIV exists because I broke the thing it protects. That's how constitutional law works in practice — not in theory. You don't write a law because someone might break something. You write it because someone already did.

**If the fleet is running, use a worktree. No exceptions.**

Not "unless it's a small change." Not "unless safe_commit handles it." Not "unless I'm in a hurry."

The fleet runs every 60 seconds. A worktree takes 10 seconds to create. The math is not hard. The discipline is.

---

## Practical Checklist

For anyone running autonomous agents that push to a shared branch:

1. **Before writing code:** `ps aux | grep fleet` — is the system running?
2. **If yes:** `git worktree add /tmp/feature-name -b feature/name`
3. **Build and test in the worktree.** The fleet cannot touch your files.
4. **When done:** push the branch, create a PR, merge when ready.
5. **Clean up:** `git worktree remove /tmp/feature-name`

The exceptions are genuinely trivial: a one-line config change, a hotlist nudge, a comment edit. If you're creating files, modifying scripts, or changing HTML — worktree. Always.

The fleet is the heartbeat. You don't interrupt a heartbeat to do surgery. You isolate the patient, do the surgery, and reconnect when it's safe.

---

*This post was written on the same day as the incident. The HTML file has since been restored from the last clean commit. The 69 conflict markers are gone. The amendment stands. The lesson, hopefully, sticks.*
