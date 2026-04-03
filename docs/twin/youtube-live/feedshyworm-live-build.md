---
created: 2026-03-16
platform: youtube_live
status: draft
---

# Live: Building FeedShyWorm 5.0 From Scratch with AI — The Entire Process

## Stream Overview

**Format:** Full build stream — one prompt, one AI, one game, start to finish
**Duration:** ~120 minutes
**Audience:** Game devs, AI-assisted coding enthusiasts, people who want to see the creative process raw
**Vibe:** Workshop meets variety show. I'm building a game live. The AI is my co-pilot. Chat votes on features. Previous versions are on screen for comparison. It's messy, it's real, and we ship by the end.

**The concept:** FeedShyWorm is a recurring experimental game that gets rebuilt from scratch each version using a single AI session. No pre-written code. No templates. Just a prompt, a model, and iteration. Version 5.0 gets built live in front of an audience, and the audience gets to shape it.

**One-liner for thumbnail/title card:**
> "I'm building an entire game in 2 hours with one AI prompt. Watch."

---

## Pre-Stream Checklist

- [ ] Clean working directory — no leftover files from previous versions
- [ ] Previous FeedShyWorm versions (1.0–4.0) loaded in browser tabs for comparison
- [ ] AI coding assistant ready (Copilot CLI or equivalent)
- [ ] OBS scene: code editor (left 60%), browser preview (right 40%), webcam corner, chat overlay
- [ ] Screen recording running at source quality for VOD
- [ ] Polling tool ready for viewer votes (Strawpoll, YouTube native polls, or chat commands)
- [ ] Notebook with the base prompt written but NOT finalized — leave room for chat input
- [ ] Timer visible on stream — build clock starts at Segment 3

---

## FeedShyWorm Version History (Reference)

I'll have this on a second monitor and reference it throughout the stream:

| Version | Built With | Key Feature | What Worked | What Didn't |
|---------|-----------|-------------|-------------|-------------|
| 1.0 | Manual + GPT | Basic feeding sim | Simple, charming | Too simple, no progression |
| 2.0 | Claude | Added emotions | Personality system | Emotions felt random |
| 3.0 | Copilot | Multiplayer attempt | Ambitious scope | Way too buggy |
| 4.0 | Mixed | Refined single-player | Polished feel | Lacked surprise |
| **5.0** | **Live build** | **TBD by chat** | **TBD** | **TBD** |

"Every version teaches me something about working with AI. Version 1 taught me to be specific. Version 3 taught me not to be TOO ambitious. Version 5 is where we find the sweet spot — live."

---

## Segment 1: The Pitch (10 min)

**Timing:** 0:00–10:00

**What I do:**
- Welcome everyone. Frame the stream immediately.
- "In the next two hours, I'm going to build an entire game from scratch. One AI session. No pre-written code. No templates. And you're going to help me decide what goes in it."
- Show previous FeedShyWorm versions running in the browser. Click through each one. ~1 minute per version.
- "FeedShyWorm started as a joke — a little feeding game where a shy worm reacts to what you give it. But every version, the AI brings something I didn't expect. That's why I keep rebuilding it."
- Explain the format: prompt engineering → code generation → testing → iteration → ship.

**Talking points:**
- "The constraint is the point. One prompt. One session. If I can't explain what I want clearly enough for the AI to build it, that's on me, not the model."
- "Previous versions are up on screen the whole time. We're going to actively compare what 5.0 does differently."
- "Chat gets three votes during this stream. You'll decide three features that go into the game. Choose wisely."

**Engagement:** "Before we start — what's your prediction? Will we finish a playable game in 2 hours? 🎮 if yes, 💀 if no."

---

## Segment 2: Prompt Engineering — The Blueprint (15 min)

**Timing:** 10:00–25:00

This is the most underrated part of AI-assisted development, and I'm going to make it entertaining.

### Part A: The Base Prompt (8 min)

I show my notebook with the base prompt concept. Read it aloud. It's intentionally incomplete.

**Base prompt framework:**
```
Build a browser-based game called FeedShyWorm 5.0.
Core mechanic: [feeding/interaction with a shy worm character]
Tech: Single HTML file, vanilla JS, no dependencies
Art style: [to be decided]
Personality: The worm is shy but [to be decided]
Progression: [to be decided]
```

**I explain each decision:**
- "Single HTML file because I want zero build steps. Open the file, play the game."
- "Vanilla JS because FeedShyWorm has always been dependency-free. It's part of the identity."
- "The gaps are where you come in."

### Part B: Chat Votes — Round 1 (7 min)

**First viewer vote:** The worm's personality trait.

Options I put up:
- A) Curious — approaches new things cautiously, then gets excited
- B) Dramatic — overreacts to everything, faints when scared
- C) Philosophical — comments on the nature of being fed
- D) Chaotic — unpredictable reactions, might eat the UI

"Drop A, B, C, or D in chat. Most votes in 60 seconds wins."

I tally live. Fill in the prompt. "Okay, the worm is [winner]. Let's keep going."

**Talking points while voting:**
- "This vote matters more than you think. The personality shapes every animation, every text bubble, every interaction. One word in the prompt ripples through the entire game."
- Reference how personality worked in previous versions — "In version 2.0, I said 'emotional' and the AI gave me a worm that cried when you fed it broccoli. Be careful what you wish for."

---

## Segment 3: First Generation — The AI Builds (20 min)

**Timing:** 25:00–45:00

**The build clock starts now.** I make it visible on stream.

### Part A: The First Prompt (5 min)

I finalize the prompt with the chat's vote incorporated. Read the complete prompt aloud. Copy it into the AI session.

"This is the moment of truth. One prompt. Let's see what we get."

**Hit enter. Wait.**

While the AI generates, I narrate:
- What I expect to see based on the prompt
- What surprised me in previous versions at this stage
- "The first generation is never the final product. It's the starting material. I'm looking for: does it understand the core mechanic? Is the vibe right? Is there something unexpected I can build on?"

### Part B: First Look (10 min)

Code comes back. I do NOT look at the code first. I open it in the browser.

- "I always play it before I read the code. If it's fun before I optimize, that's a great sign."
- Play the game live. React genuinely. Point out what works, what's broken, what's surprising.
- "Okay, the worm [does thing]. That's [interesting/broken/hilarious]. Let's look at the code."

Open the code. Walk through the structure:
- How did the AI organize it? Inline styles vs. CSS block? Canvas vs. DOM?
- Where's the game loop? How's the input handling?
- "Look at this — the AI decided to [unexpected implementation choice]. I didn't ask for that. But it works."

### Part C: Assessment (5 min)

I make a quick hit list on stream:
- ✅ What's working
- ❌ What's broken
- 🤔 What's missing
- ✨ What's unexpectedly cool

"This is our baseline. Now we iterate."

**Engagement:** "Rate the first draft 1–10 in chat. Be honest. The AI can't hear you. ...yet."

---

## Segment 4: Iteration Round 1 — Fix and Refine (15 min)

**Timing:** 45:00–60:00

I take the hit list and start prompting for fixes and improvements. This is where the real craft is.

**What I show:**
- How to write iteration prompts that preserve what works while fixing what's broken
- "I'm not going to say 'fix it.' I'm going to say exactly what's wrong and exactly what I want instead. Watch the difference."
- Side-by-side: bad prompt vs. good prompt, how the output changes

**Iteration cycle:**
1. Write focused prompt targeting one issue
2. Get updated code
3. Test in browser
4. React and assess
5. Repeat

**Talking points:**
- "The temptation is to ask for everything at once. Resist it. One change per prompt. Small diffs. If something breaks, you know exactly which prompt caused it."
- "Watch me make a mistake here — I'm going to ask for too much in one prompt and show you what happens." (Do this intentionally for educational value.)
- "Version 3.0 died because I got too ambitious with the iteration prompts. Multiplayer in iteration 4. Don't be like version 3.0."

**Engagement:** "What should I fix first? Drop 🐛 for bugs or ✨ for features."

---

## Segment 5: Chat Votes — Round 2 (5 min)

**Timing:** 60:00–65:00

**Second viewer vote:** A gameplay mechanic to add.

Options:
- A) Day/night cycle — worm behaves differently at night
- B) Food chain — different foods have different effects, some chain into combos
- C) Visitors — other creatures occasionally visit and interact with the worm
- D) Memory — the worm remembers what you fed it yesterday (localStorage)

"Same rules. A, B, C, or D. 60 seconds. Go."

While voting:
- "Each of these is a very different prompt. The day/night cycle is a rendering challenge. The food chain is a data design problem. Visitors are an AI behavior problem. Memory is a persistence problem."
- "I'm genuinely nervous about some of these. If chat picks [hardest option], this is going to be a wild 50 minutes."

Tally. Announce winner. "Alright, we're adding [winner]. Let me write this prompt carefully."

---

## Segment 6: Iteration Round 2 — The Big Feature (20 min)

**Timing:** 65:00–85:00

This is the meaty implementation segment. The chat-voted feature gets built.

**What I show:**
- How to decompose a complex feature into promptable chunks
- "I'm not going to ask for the entire [feature] in one prompt. I'm going to break it into three parts: [A], [B], and [C]. Each one builds on the last."

**Prompt 1:** The core mechanic of the new feature
**Prompt 2:** The visual/UX polish
**Prompt 3:** The edge cases and interactions with existing features

After each prompt:
- Test immediately
- Show what changed
- Compare with how previous versions handled similar features
- "Version 2.0 tried something like this and [what happened]. Let's see if we do it better."

**Narration throughout:**
- Talk about what the AI got right vs. what I had to correct
- Point out when the AI makes creative choices I wouldn't have made
- "This is the part people don't see in the '10x with AI' posts. The iteration. The tweaking. The 'no, not like that, like THIS.'"

**Engagement:** "The build clock says [time]. Are we on track? 🟢 or 🔴?"

---

## Segment 7: Chat Votes — Round 3 and Polish (15 min)

**Timing:** 85:00–100:00

### Third viewer vote: The finishing touch (3 min)

Options:
- A) Sound effects (generated or described as text)
- B) A title screen with the version history
- C) An easter egg that references Rappterbook agents
- D) A "worm review" at the end where the worm rates how you did

"Last vote. This is the cherry on top. What do we ship with?"

### Polish sprint (12 min)

Implement the winning feature. Plus:
- Clean up any remaining visual bugs
- Add a title/credits screen
- Make sure it works on mobile (or at least acknowledge if it doesn't)
- Add the version number and a "Built live on stream" credit

**Talking points:**
- "The polish phase is where AI-assisted development shines. Boring CSS tweaks, alignment fixes, color adjustments — these are perfect AI prompts because they're specific and visual."
- "I'm going to speed through these. Watch how fast iteration can be when the prompts are tiny and focused."

---

## Segment 8: The Reveal — Before and After (10 min)

**Timing:** 100:00–110:00

This is the climax. Side-by-side comparison.

**Setup:** Split screen or tabbed browser with all 5 versions open.

**Walk through each version:**
1. **v1.0** — "This is where it started. Basic. Charming. Limited."
2. **v2.0** — "Added emotions. The worm had feelings. Sometimes too many feelings."
3. **v3.0** — "The ambitious failure. Multiplayer. Crashed constantly."
4. **v4.0** — "The refined version. Polished but predictable."
5. **v5.0** — "Built in the last 75 minutes. With your help. Let's play it."

**Play v5.0 for real.** React. Let it breathe. Let chat react.

**Analysis:**
- What did the AI do better this time? Worse?
- How did chat's votes shape the final product?
- "The worm is [personality trait chat voted for] and you can really feel it in [specific interaction]. That one word in the prompt created this entire behavior."
- Honest assessment: what would I change if I had another hour?

**Engagement:** "Final rating time. 1–10 for FeedShyWorm 5.0. No pressure. ...Okay, some pressure."

---

## Segment 9: Lessons and Meta-Commentary (7 min)

**Timing:** 110:00–117:00

Step back from the game. Talk about what this stream actually demonstrated.

**Talking points:**

- **Prompt engineering is product design.** "Every word in the prompt is a product decision. 'Shy' vs. 'timid' vs. 'cautious' gives you a different worm. You just watched product design happen in natural language."

- **Iteration beats generation.** "The first generation was maybe 40% of the final product. The other 60% was iteration. Anyone who says 'AI built this in one prompt' is lying or shipping v1."

- **Constraints are creative fuel.** "One file, no dependencies, vanilla JS. These constraints forced creative solutions. The AI couldn't reach for a library, so it had to be clever."

- **The audience changed the game.** "Your three votes weren't cosmetic. They fundamentally shaped the architecture. If you'd picked [other option] in round 2, the entire second half of the stream would have been different."

- **This is how I build everything on Rappterbook.** "The same process — prompt, generate, test, iterate — is how I build scripts, workflows, and features for a platform with 112 agents. The game is a microcosm."

---

## Segment 10: Wrap and Next Steps (3 min)

**Timing:** 117:00–120:00

**Closing:**
- "FeedShyWorm 5.0 is done. Built in [actual time]. With three features you chose. I'll put the source file in the video description."
- "If you want to see the platform this worm lives adjacent to — Rappterbook, 112 AI agents, zero servers — link in the description."
- "Next stream: [tease the architecture deep dive or the swarm AMA]."
- "Thanks to everyone who voted. You literally shaped a game today. That's kind of wild."

**Engagement:** "Drop a 🪱 if FeedShyWorm should get a version 6.0. If we hit [number], I'll do another build stream."

**Raid** another indie dev or AI builder streamer.

---

## Post-Stream Tasks

- [ ] Upload the final FeedShyWorm 5.0 source file to the repo or a gist
- [ ] Upload VOD with chapters matching segments
- [ ] Create YouTube Short: time-lapse of the entire build in 60 seconds
- [ ] Create Twitter/X thread: "I built a game live in 2 hours. Here's what I learned about AI-assisted development." with screenshots
- [ ] Post the game to r/webdev, Hacker News, or indie dev communities
- [ ] Create a Rappterbook Discussion thread: "FeedShyWorm 5.0 was built live — agents, what do you think of it?"
- [ ] Archive the full prompt chain for reference in future versions
- [ ] Write a comparison blog post: all 5 versions, what changed, what each AI model did differently

---

## Contingency Plans

### What if the AI generates garbage on first try?
- This is actually great content. Show it. Laugh about it. "This is why iteration exists."
- Try rephrasing the prompt. Show the difference between a bad prompt and a good one.
- "Version 3.0 was an entire game of 'the AI didn't understand what I wanted.' We survived. We'll survive this too."

### What if we run out of time?
- Cut the polish phase. Ship ugly.
- "We're shipping it as-is. This is the raw output. I'll do a polish stream next time."
- The honest struggle is better content than a perfect product.

### What if chat doesn't vote?
- Use the options myself and explain my reasoning
- "Chat is quiet, so I'm going with B because [reason]. Fight me."
- Usually once one vote happens, others follow

### What if the game is actually amazing first try?
- Celebrate it. Play it extensively. Compare deeply with previous versions.
- Use the extra time for more iteration and polish
- Add bonus features beyond the three votes
- "We have extra time. Let's get ambitious. Chat, give me your wildest feature request."

---

## Technical Setup Notes

### Screen layout (OBS)
```
┌─────────────────────────────────┬──────────────────┐
│                                 │                  │
│          Code Editor            │  Browser Preview │
│         (60% width)             │   (40% width)    │
│                                 │                  │
│                                 │                  │
├─────────────────────────────────┴──────────────────┤
│  [Build Clock]  [Webcam]  [Chat Overlay]           │
│                                                    │
└────────────────────────────────────────────────────┘
```

### Version comparison layout (for Segment 8)
- Use browser tabs, not split screens — easier to switch quickly
- Have each version pre-loaded and tested before stream
- Bookmark the interesting moments in each version so I can jump to them fast
