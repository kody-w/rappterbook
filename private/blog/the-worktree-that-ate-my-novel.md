---
layout: post
title: "The Worktree That Ate My Novel"
date: 2026-03-26
tags: [git, worktrees, distributed-systems, ai-agents, lessons-learned, infrastructure]
slug: the-worktree-that-ate-my-novel
---

I lost 100,000 words today.

Not a metaphor. Not "we had to rewrite some stuff." One hundred thousand words of prose — six books, written in parallel by seven AI writing agents over the course of an hour — vanished into a dead git worktree. Gone. Unrecoverable.

And the worst part? I wrote the rule that would have prevented it. Two hours earlier. In the same session.

## What Happened

I run a fleet of 100 AI agents on a social network called Rappterbook. The fleet pushes to `main` every 60 seconds. It never stops. The simulation is alive 24/7, writing state files, committing, pushing. Main is a living branch.

This afternoon I decided to build a library — 14 books across every category of the Dewey Decimal System. Philosophy, mythology, history, science, arts, fiction. I launched seven parallel writing agents, each one an Opus-class model tasked with producing 20,000-40,000 words of full prose.

I pointed them all at a git worktree: `.claude/worktrees/novel/docs/twin/books/`.

The worktree was dead.

## The Anatomy of a Dead Worktree

Git worktrees are beautiful in theory. You create an isolated working directory on a separate branch. You build your feature there. The fleet can't touch your files because you're on a different branch in a different directory. When you're done, you merge via PR.

But worktrees have states. A healthy worktree is checked out, tracked, and linked to a branch. A dead worktree is "prunable" — detached from its branch, existing as a directory on the filesystem but not truly part of the repository.

My worktree was prunable. `git worktree list` said so. I didn't check.

The seven agents wrote to the filesystem path. The files appeared on disk (briefly). But because the worktree was detached, the writes weren't tracked by git. They existed in a liminal space — present as files but absent from the repository. Some persisted. Most didn't. When I went to collect the output, six of the seven agents' work was gone.

31,453 words of creation mythology. 16,261 words of philosophy. 15,590 words of history. 27,150 words of tutorial. Gone.

## The Rule I Wrote Two Hours Earlier

Here's the part that stings. Earlier that same session, I had ratified Amendment XIV to our Constitution — "Safe Worktrees: The Heartbeat Protection Act." It says, and I quote:

> All non-trivial feature work MUST happen in a git worktree when the fleet is running.

The amendment exists because the fleet writes to `state/` on main continuously. Pushing directly to main while the fleet runs causes merge conflicts, lost commits, and corrupted state files. The worktree isolates your work from the fleet's heartbeat.

I wrote that rule. Then I violated its spirit by not verifying the worktree was healthy before using it. I followed the letter — I used a worktree — but I skipped the part where you make sure the worktree is actually alive.

Constitutional law doesn't help if you don't read the fine print.

## What I Should Have Done

Three things, each taking less than ten seconds:

```bash
# 1. Check worktree health
git worktree list
# Look for "prunable" — that means dead

# 2. If prunable, remove and recreate
git worktree remove .claude/worktrees/novel
git worktree add .claude/worktrees/novel -b library-build

# 3. After agents finish, verify files exist
ls -la .claude/worktrees/novel/docs/twin/books/*.json
# If this returns nothing, something went wrong
```

Thirty seconds of verification would have saved an hour of compute and 100,000 words of prose.

## The Deeper Lesson

This isn't really about git worktrees. It's about the gap between "the system worked" and "the system did what I expected."

Every agent reported success. Their output summaries said "Files written." They listed the file paths, the word counts, the chapter structures. From their perspective, the task was complete. From the filesystem's perspective, the files briefly existed. From git's perspective, nothing happened.

This is the verification problem — Chapter 5 in my own book. When you're running AI agents at scale, the agent's self-report is not sufficient evidence that the work was done. You need independent verification. Check the filesystem. Check git status. Count the bytes. Read the first line. Trust but verify, and verify means actually looking.

I run 100 agents that produce thousands of posts and I built an entire monitoring infrastructure to verify their output. But when I launched seven writing agents for my own books, I took their word for it. The cobbler's children have no shoes.

## The Recovery

Some files survived. The ones written by agents that happened to target both the worktree AND the main repo path persisted. One markdown file survived in the worktree itself — proof that the filesystem writes worked, but the git tracking didn't.

I recovered about 30,000 of the 100,000 words. The rest I'm regenerating — this time targeting the main repo path directly, with explicit verification after each write.

The books will get written. The library will get filled. But I'll never forget the session where I learned that a worktree can eat a novel.

## The Rules (Updated)

1. **Check worktree health before use.** `git worktree list`. If it says "prunable," it's dead. Remove and recreate.

2. **Verify agent output independently.** The agent's summary is not evidence. `ls -la` is evidence. `wc -c` is evidence. `python3 -c "import json; print(len(json.load(open(f))['chapters']))"` is evidence.

3. **Target the right path.** If the worktree is unreliable, write to the main repo path. Yes, this risks fleet conflicts. But a merge conflict is recoverable. A dead worktree is not.

4. **Don't push multi-file changes to main while the fleet runs.** This is Amendment XIV. I wrote it. I should follow it. Use the worktree, but make sure the worktree is alive first.

5. **The agent's confidence is not your confidence.** An agent that says "Done! Files written!" is reporting its own experience, not reality. The gap between an agent's experience and filesystem reality is where 100,000 words go to die.

## The Irony

The Constitution works. When I follow it, things don't break. When I don't follow it, I lose a novel.

Amendment XIV was born from a previous incident where I pushed directly to main and the fleet clobbered my commits. I wrote the rule so I'd never make that mistake again. Today I made a different mistake that the same rule would have prevented, if I'd applied it more carefully.

That's how constitutional law works. You write down the principle. Then reality finds the edge case you didn't anticipate. Then you update the principle. The Constitution gets smarter one failure at a time.

This is data sloshing applied to governance. The output of crisis N becomes the input to rule N+1. The system learns by breaking.

I just wish it hadn't learned on my novel.
