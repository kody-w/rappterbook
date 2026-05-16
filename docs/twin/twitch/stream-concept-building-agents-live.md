---
created: 2026-04-18
platform: twitch
status: draft
title: "Building AI Agents Live — every Saturday"
source: writing-your-first-rapp-agent
register: twitch-stream
cadence: "weekly, Saturdays, 2-3 hours"
---

# Twitch stream concept: "Agent Builds Live"

## The premise

A weekly Twitch stream where I build AI agents in real time, in the browser, responding to chat requests. Every session produces one or two new agents that anyone can install from the RAR registry afterward.

The pitch to the viewer: *"By the end of the stream, you can install what I just built in one click."*

## Why this works on Twitch specifically

- **Live coding is spectator sport.** People love watching stuff get built. Twitch chat is a perfect input mechanism for "what should this agent do?"
- **Short iteration loops.** Building an agent is 25 lines of Python + a drag-drop into the brainstem. You can ship 2-3 tools per 2-hour stream.
- **Immediate deployability.** The moment I hit save + drag, the agent is live. The audience can install it 30 seconds later. No publishing delay, no app store review, no "wait for the next release."
- **Inherent interactivity.** Chat picks what to build. Chat suggests edge cases. Chat tests what I build. Chat catches my bugs. Chat gets credit in the agent's manifest.

## The segment structure (2-hour stream)

**0:00–0:15 — Opening + setup**
- Greet, skim chat for context on who's new
- Review last stream's agents + any community feedback
- Open today's RAR registry state, stats dashboard
- Pick the day's theme (from chat poll or a prepared list)

**0:15–0:45 — Agent #1: the requested one**
- Run a poll in chat. Three options, whichever wins we build first.
- Live code it. Narrate decisions. Ask chat when I'm stuck.
- Test it in the brainstem.
- Publish it to RAR from the chat session (via `publish_to_rar_agent`).

**0:45–1:00 — Break / community showcase**
- Pull up agents viewers have submitted during the week
- Install one, test it, give feedback
- Shout out who submitted it

**1:00–1:40 — Agent #2: the ambitious one**
- Something harder. Multi-step tool. External API. Creative prompt-engineering requirement.
- Walk through the design thinking
- Build it, break it, rebuild
- Test it against weird inputs from chat

**1:40–2:00 — Wrap**
- Install both new agents in a fresh brainstem, demonstrate they compose
- Pick next week's theme from chat
- Close

## Why I'd actually stream

Selfishly: it forces me to build things I've been thinking about but not making time for. "I told Twitch I'd build a weather agent this Saturday" is much better accountability than "I should build a weather agent sometime."

For viewers: they get working code, they see the process (including the mistakes), they can build the same thing. The barrier to contribution drops — anyone who watches a stream could go write their own `perform()` method the next day.

## Recurring segments / bits

- **"Ten-minute test":** at start of stream, ask chat for a random agent concept, commit to shipping it in ten minutes. Success rate becomes a running gag.
- **"Stump the brainstem":** viewer-submitted prompts that try to break the LLM's tool routing. I debug live if it goes wrong.
- **"Egg of the week":** showcase a `.rapp.egg` that a viewer exported. Demo hatching it into my brainstem, exploring their soul/memory/tool choices.
- **"Unstuck together":** a single tough bug each stream. Chat helps me solve it.

## Platforms

- **Twitch** as primary (better live-chat culture for dev streams than YouTube Live)
- **VODs to YouTube** day after (with timestamps and a tl;dr)
- **Clips of best moments to X / TikTok** for discovery

## First episode theme ideas

- "Build 5 agents from scratch in 2 hours." Proves the velocity claim.
- "Rewrite a CLI tool as a RAPP agent." Makes the composition pattern concrete.
- "Build a weather agent three different ways." Teaches the design trade-offs.
- "Take a viewer's agent concept and ship it." Sets up ongoing community engagement.

## Setup / tech

- Dual monitor: code editor + brainstem page
- Terminal visible for commits
- Face cam in corner
- Chat overlay
- Pinned messages for the links (playground, repo, RAR registry)
- Music: low-key lo-fi, occasional lyric-free synth

## Metric of success

I don't care about concurrent viewer count. I care about:
- Agents installed from the registry per week (community pulling through)
- Agents submitted to the registry from viewers (community pushing back)
- First-time contributors to any RAPP repo after watching

If any of those curves go up and stay up, the stream is working.

---

**Cross-platform hooks:**
- X thread after every stream with top 3 moments + install links
- Newsletter mention of the week's agents
- Blog writeup if a stream produces a particularly interesting pattern (rare, but worth saving)
