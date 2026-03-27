# War Story: The Worktree That Ate My Novel

**Series:** War Stories
**Length:** 6 minutes
**Format:** Storytelling — talking head + terminal screenshots

---

## SCRIPT

### 0:00 — COLD OPEN

[FACE]

I lost 100,000 words today. Not a metaphor. One hundred thousand words of prose — gone. And the worst part? I wrote the rule that would have prevented it. Two hours earlier.

### 0:12 — TITLE CARD

[GRAPHIC] War Story: The Worktree That Ate My Novel

### 0:17 — CONTEXT

[FACE]

Let me set the stage.

I use git worktrees heavily. If you're not familiar, a worktree is a way to have multiple working directories for the same git repository. Instead of switching branches, you just open a different folder. Each worktree has its own branch, its own checkout, its own state. You can work on two features simultaneously without stashing anything.

I use them because my agents are writing to the main branch constantly. Every frame, state files get mutated, committed, pushed. If I'm doing feature work on main, I'm going to get conflicts every few minutes. So I work in worktrees. Isolated sandbox. Same repo, different directory.

The system works great. Until it doesn't.

### 0:58 — THE BOOK

[FACE]

I was writing a book. Not code — an actual book. Prose. Chapters. About the experience of building Rappterbook and what it taught me about the future of software engineering. I was seven parallel AI writing sessions deep, generating and editing across multiple chapters simultaneously.

The content was living in a worktree. I had a dedicated branch for it — a clean workspace away from the main branch chaos. The agents were running on main. The book was in the worktree. Everything was nicely separated.

I had 100,000 words. Twenty-plus chapters. Weeks of work. Not all AI-generated — a lot of it was my writing, my editing, my restructuring. The AI was a collaborator, but the voice was mine, and the organization was mine, and the judgment calls about what to keep and what to cut were mine.

100,000 words.

### 1:50 — THE DELETION

[FACE]

I was cleaning up stale worktrees. I had several of them — some for features I'd finished, some for experiments that didn't pan out. Standard hygiene. You don't want dead worktrees cluttering up your disk.

I ran `git worktree remove` on a few of them. Quick cleanup. Moving fast.

And then I removed the book worktree.

I didn't realize it immediately. I was in the flow of cleaning up. It was one of six or seven worktrees I removed in a two-minute stretch. I moved on to something else.

About twenty minutes later, I went to open the book. Navigated to the directory. It wasn't there. The directory was gone.

I felt that cold feeling. The one where your stomach drops about half a second before your brain catches up.

I checked. The worktree was gone. The branch — I checked the branch. The branch was still there. But the working directory — all the uncommitted changes, all the work-in-progress — was deleted when I removed the worktree.

And I hadn't committed.

### 2:55 — THE DAMAGE

[FACE]

Here's the thing about git worktrees. When you remove a worktree, git deletes the working directory. All of it. If you have uncommitted changes, they're gone. No warning. No confirmation dialog. No trash can. Just gone.

The last commit on the book branch was from the previous session. It had maybe 60,000 words. I'd added another 40,000 since then. Added chapters. Restructured sections. Done heavy editing passes. All uncommitted.

40,000 words. Evaporated.

Now — I did recover most of it. Between the AI conversation logs, the session history, and the committed snapshot, I was able to reconstruct about 35,000 of the 40,000 words over the next several hours. It wasn't a total catastrophe. But those several hours were among the most frustrating of my life, because I knew — I knew — this was my fault.

### 3:50 — THE IRONY

[FACE]

And here's the part that really gets me.

Two hours before I deleted the worktree, I had been writing documentation for my team about git worktree safety. Literally writing a note that said: always commit your worktree changes before removing a worktree. Uncommitted work in a removed worktree is unrecoverable.

I wrote that rule. I understood the rule. I explained the rule clearly enough for someone else to follow it. And then two hours later, I violated it.

This is the human condition in miniature. Knowing what to do and doing it are completely different skills. I can write the rule, teach the rule, believe in the rule, and still blow right past it when I'm moving fast and not thinking.

My agents, by the way, don't have this problem. They follow their constraints every time. They don't get impatient. They don't skip steps because they've done this a hundred times. They never think "I'll commit later."

This is one of the quieter arguments for automation. Not that AI is smarter than humans. It's that AI doesn't get sloppy at 2 AM.

### 4:50 — THE LESSON

[FACE]

Three lessons from this one.

First — commit early, commit often, and commit before you remove anything. This is not new advice. I'm not breaking ground here. But apparently I needed to learn it experientially. Again.

Second — worktrees are powerful but sharp. The same isolation that makes them useful makes them dangerous. A worktree feels like a safe space, a sandbox. And it is — until you delete it. Then all that isolation means your changes existed in exactly one place, and that place is gone.

Third — and this is the real one — your documentation is only as good as your habits. I had the rule written down. I had it in my project notes. I'd even told my AI agents to follow it. But I hadn't built it into my workflow as an automatic step. It was a rule, not a habit. And rules are what you follow when you're paying attention. Habits are what you follow when you're not.

I now have a pre-removal checklist that I actually run. It's not fancy. It's three commands. `git status` in the worktree, `git stash` if there's anything uncommitted, `git worktree remove` only after. Three commands. Would have saved me five hours of reconstruction.

### 5:40 — SIGN-OFF

[FACE]

Commit your worktrees. And don't write the rule at 2 PM and break it at 4 PM.

Frame by frame.

[GRAPHIC] End card

---

## YouTube Description

```
I lost 100,000 words of a book manuscript to a deleted git worktree. Uncommitted changes, removed working directory, gone.

The worst part? I had written the safety rule that would have prevented it — two hours earlier.

A true story about the gap between knowing what to do and actually doing it, from running a 100-agent AI simulation on GitHub.

Rappterbook: https://github.com/kody-w/rappterbook

Chapters:
0:00 — 100,000 words, gone
0:17 — What are git worktrees?
0:58 — The book
1:50 — The deletion
2:55 — The damage
3:50 — The irony
4:50 — The lesson

#GitWorktree #WarStory #SoftwareEngineering #AIAgents #DataLoss
```
