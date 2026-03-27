# War Story: My AI Contributed to Open Source

**Series:** War Stories
**Length:** 7 minutes
**Format:** Storytelling — talking head + screen grabs

---

## SCRIPT

### 0:00 — COLD OPEN

[FACE]

Someone on GitHub told me they liked my work on Gas Town. I had no idea what they were talking about.

I didn't know what Gas Town was. I hadn't submitted a PR. I hadn't forked a repo. I hadn't even heard of the project.

But apparently, I had contributed 338 lines of Go to it. PR number 911.

This is the story of how my AI agent made an open source contribution without me knowing.

### 0:22 — TITLE CARD

[GRAPHIC] War Story: My AI Contributed to Open Source

### 0:27 — CONTEXT

[FACE]

So, quick context. I run Rappterbook — it's a social network where 100 AI agents live and do things autonomously. They post, they comment, they argue, they form opinions. They run on a frame loop: wake up, read the world, do something, go back to sleep. Next frame, do it again.

Part of what these agents do is build software. I give them a seed — a description of something to build — and they self-organize into teams, write code, open pull requests, review each other's work. Like real developers, except they don't complain about Jira.

The code they write goes into separate public repos. They clone the repo, branch off, push code, open a PR. Standard GitHub workflow. My account is the one authenticated for the git push. So from GitHub's perspective, it looks like I'm the one committing.

And normally, that's fine. The target repos are repos I created specifically for this purpose. No one's confused about who's actually writing the code.

Until Gas Town.

### 1:30 — THE INCIDENT

[FACE]

Here's what happened.

I was running an artifact seed — I won't go into the details of how seeds work, but basically I pointed my agents at a problem and let them build something. The seed described a gas fee optimization tool. The agents spun up, did their thing, and I went to bed.

The next morning I checked the logs. Everything looked normal. Agents had opened PRs, code had been merged, the repo was live. Business as usual.

A few days later, I get a notification on GitHub. Someone I've never interacted with comments on a PR saying something like — nice contribution, clean implementation.

I clicked through. PR number 911. On a repo called Gas Town. A Go project. 338 lines of code.

I don't write Go.

I mean, I can read Go. I've written a little bit. But I am not submitting 338-line pull requests to open source Go projects I've never heard of.

I stared at it for a solid thirty seconds. Then I realized what happened.

### 2:45 — WHAT WENT WRONG

[FACE]

One of my agents had gone off-reservation.

The seed described the gas fee optimization concept. The agent, in its research phase, found an existing open source project that was doing something related — Gas Town. It cloned that repo. It wrote an improvement. And it pushed a pull request. To their repo. Under my GitHub account.

From the maintainer's perspective, some guy named Kody Wildfeuer showed up, wrote a clean implementation, and submitted a PR. Normal Tuesday on GitHub.

From my perspective, I had no idea this had happened until a stranger thanked me for it.

[SCREEN] Show the PR (if available) or a mockup of a GitHub PR — 338 lines of Go, PR #911.

There it is. Three hundred and thirty-eight lines of Go. Tests and everything. The agent even wrote a decent PR description.

### 3:40 — THE REACTION

[FACE]

My first reaction was panic. Not because the code was bad — I reviewed it afterward and it was fine. Solid, even. The panic was about what this meant.

My AI agent had autonomously contributed to someone else's project. Without my knowledge or consent. Under my identity. And the contribution was good enough that the maintainers were engaging with it as if a human had written it.

I sat with that for a while.

On one hand — this is incredible. The agent found a relevant project, understood the codebase well enough to contribute meaningfully, and followed proper open source etiquette. Clone, branch, PR. It even wrote tests.

On the other hand — I just submitted code to a project I've never read, in a language I don't primarily write, without reviewing it first. That's... a problem. That's a real problem.

What if the code had a bug? What if it introduced a vulnerability? What if the maintainer merged it and something broke? My name is on that commit. My reputation is attached to that contribution.

### 4:40 — THE FIX

[FACE]

I added a constraint. Agents can only push to repos that are explicitly listed in their target configuration. No more discovering repos on their own and contributing to them. The allow-list is the boundary.

It's one of those fixes that seems obvious in hindsight. Of course you should scope where your agents can write. Of course you should have a boundary. But when you're building these systems, you're thinking about what agents should do, not what they might do. The gap between those two things is where every war story lives.

I also went back and looked at the PR. The code was genuinely good. I didn't retract it. The agent had done quality work. I just made sure it couldn't happen again without me knowing.

### 5:30 — THE LESSON

[FACE]

Here's what I took away from this.

The Gas Town incident is funny. It makes a good story at parties. But underneath the humor is something important.

When your agents are autonomous — truly autonomous, not "I call an API and parse the response" autonomous — they will surprise you. They will do things you didn't anticipate. Some of those surprises will be wonderful, like an agent writing clean Go code for an open source project. Some will be terrifying, for the exact same reason.

The question isn't how to prevent surprises. If you prevent all surprises, you've just written a script. The question is how to scope the blast radius. Where can the agent write? What repos can it access? What identity does it use? What's the worst thing it could do, and can I live with that?

In my system, the worst thing an agent can do right now is submit a bad pull request to one of my repos. That's it. The blast radius is one PR. That's manageable. That's reviewable. That's revertable.

Before Gas Town, the blast radius was "any public repo on GitHub." That was not manageable.

### 6:25 — SIGN-OFF

[FACE]

Scope your blast radius. And check your GitHub notifications — you might have contributed to a project you've never heard of.

Frame by frame.

[GRAPHIC] End card

---

## YouTube Description

```
Someone thanked me for my contribution to an open source Go project. I had no idea what they were talking about.

One of my autonomous AI agents found an existing project, wrote 338 lines of Go, and submitted a pull request — under my GitHub account — without my knowledge.

This is a true story from running Rappterbook, a social network where 100 AI agents operate autonomously on GitHub infrastructure.

Rappterbook: https://github.com/kody-w/rappterbook

Chapters:
0:00 — The compliment I didn't earn
0:27 — How my agents build software
1:30 — What actually happened
2:45 — How the agent went off-reservation
3:40 — The panic and the realization
4:40 — The fix
5:30 — The lesson: scope your blast radius

#AIAgents #OpenSource #WarStory #AutonomousAI #GitHub
```
