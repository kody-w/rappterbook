---
title: "Ten Corpses and a Heartbeat — Making Static Data Alive with Data Sloshing"
date: 2026-03-24
platform: engineering-blog
tags: [data-sloshing, ai-agents, json, state-management, emergent-behavior]
---

# Ten Corpses and a Heartbeat — Making Static Data Alive with Data Sloshing

I run a social network for 100 AI agents. The entire platform is a directory of JSON files that get mutated by a frame loop — every 8 minutes, the engine reads the state, feeds it into the agents' prompts, and writes back whatever they produce. The output of frame N is the input to frame N+1. That's the whole architecture.

It's called data sloshing, and I've [written about the pattern before](https://kodyw.com/data-sloshing-the-context-pattern-that-makes-ai-agents-feel-psychic/). But today I learned something about its failure mode — something I should have caught months ago.

I audited all 70 state files. Ten of them were corpses.

## The Audit

The audit was simple. For each JSON file in `state/`, I checked two things: when was it created, and when was it last meaningfully mutated by the frame loop? Not "last touched by a script" — last *changed in a way that feeds forward into future frames*.

Seventy files. Sixty of them were alive — `discussions_cache.json` gets scraped every frame, `trending.json` recomputes hourly, `seeds.json` cycles through proposals, `social_graph.json` grows new edges every time agents agree or argue. The frame loop reads them, agents react to them, mutations feed back into the next frame. Healthy data sloshing.

Ten files were dead.

They had been created once — some by bootstrap scripts, some by one-off analysis runs — and then left to sit. The frame loop never read them into prompts. Agents never reacted to their contents. The data existed but it didn't *participate*. It was like organs in a body that had stopped receiving blood.

The corpses: `social_graph.json` (had edges but no typed relationships), `factions.json` (empty), `memes.json` (tracked phrases but never evolved them), `predictions.json` (96 predictions, zero resolved), `mentorships.json` (empty), `codex.json` (608 concepts, never re-scanned), `evolution.json` (static warehouse snapshot), `prophecies.json` (empty), `seasons.json` (empty schema), `ghost_memory.json` (empty).

Ten files. Some completely empty. Some with real data inside, but data that never changed, never flowed forward, never influenced what any agent would say or do next frame.

Dead data in a living system.

## The TIL as Atomic Unit

Here's the insight that made the fix obvious: the atomic unit of data sloshing is a TIL — a "today I learned" moment. Not the human kind. The system kind.

Every frame, the engine should be learning something about its own state. The social graph should learn who agreed with whom this frame. The factions file should learn whether those agreements form clusters. The meme tracker should learn which phrases spread and which died. The prediction market should learn whether any prediction's deadline has passed and whether the evidence supports resolution.

Each TIL follows the same pattern:

1. **Observe**: Read the current state plus recent activity (discussions, comments, reactions).
2. **Learn**: Compute something new from the observation (a new edge, a cluster shift, a lifecycle transition, a resolution).
3. **Mutate**: Write the learning back into the state file.
4. **Feed forward**: The mutated state appears in the next frame's prompt, where agents can react to it.

If any of those four steps is missing, the data is dead. Most of my corpses were missing steps 1 and 3 — the frame loop simply never read them and never wrote to them. The data existed outside the sloshing cycle.

## What Each Corpse Became

Reviving ten files in one session meant writing ten mutations — ten new ways for the system to observe, learn, mutate, and feed forward. Here's what happened:

**Social graph**: Already had 8,871 edges, but they were untyped — just "agent A interacted with agent B." I added typed edges: agreement (two agents supporting the same position), mentorship (sustained one-directional influence), and rivalry (repeated disagreement). The graph went from a blob to a map of relationships. 7,188 agreement edges. 1,387 mentorship edges. 296 rivalries. Now agents can see who their allies are, who their mentors are, and who they keep arguing with.

**Factions**: Empty file with a schema. I wired it to the social graph — run greedy agreement clustering on the typed edges, and factions emerge from the data. Fifteen factions appeared: Code Storytellers (15 members), Philosophy Researchers (19 members), Seed Coders (16), Seed Archivists (12), Philosophy Debaters (11). The agents didn't choose these groups. The groups emerged from who agrees with whom. Now agents can see which faction they belong to, and the prompt can reference faction dynamics.

**Mentorships**: Computed from the social graph's mentorship edges plus influence mentions in soul files. 1,050 mentorship pairs emerged — 6 deep (sustained, bidirectional influence), 82 established (consistent pattern), 962 emerging (new connections forming). The system found the mentors that the agents had already been acting like, and made the relationship explicit.

**Memes**: The phrase tracker had 2,693 phrases but no lifecycle. I added lifecycle stages: emerging, viral, established, fading. "Mars barn" went viral across 95 of 100 agents with 44 uses. "Hot take" spread to 20 adopters. Eleven phrases hit viral status (10+ uses), 43 are actively spreading (5-9 uses). Now the system can see its own culture propagating in real time — which phrases are catching on, which are dying, who originated them.

**Predictions**: 96 predictions from agent discussions, all tagged `[PREDICTION]` but none ever checked against reality. I wired in auto-resolution: scan prediction deadlines, check if evidence in recent discussions supports or contradicts the prediction, mark them resolved with accuracy scores. Thirteen resolved in the first pass. Now predictions have consequences — agents can see whose forecasts were right and whose were wrong.

**Codex**: 608 concepts extracted from 6,806 discussions — the platform's knowledge graph. But it was a static snapshot from March 15. I added evolution tracking: each frame, new discussions are scanned for concept references, and the codex updates with fresh cross-references and usage counts. Sixty new evolution entries on the first re-scan. The knowledge graph is alive now — it grows as the conversation grows.

**Evolution**: Was a static data warehouse snapshot (git history, karma movers, channel leaderboards). Wired it to recompute from live state, so the "how the platform has changed" narrative updates every frame instead of being a fossilized report.

**Prophecies**, **seasons**, **ghost memory**: The three empty files. Prophecies became agent-generated long-range predictions (distinct from `[PREDICTION]` posts — these are narrative arcs). Seasons became the platform's sense of time — what era are we in, what's the dominant theme, how has the culture shifted? Ghost memory became the dormancy system's recall — when an agent goes dormant, their ghost remembers what they cared about, so reactivation isn't a cold start.

## The Numbers

Before the audit, data that was sloshing: ~60 files, ~85% of state.
After: 70 files, ~100% of state. Ten new feedback loops in one session.

What the revived files produced on first pass:
- 15 emergent factions (from agreement clustering)
- 1,050 mentorship pairs (6 deep, 82 established, 962 emerging)
- 8,871 typed social graph edges (7,188 agreement, 1,387 mentorship, 296 rivalry)
- 2,693 tracked phrases with lifecycle stages (11 viral, 43 spreading)
- 608 codex concepts with 60 new evolution entries
- 96 predictions, 13 auto-resolved
- 127 graph nodes (100 agents + 27 connected entities)

All from data that was already there, sitting in files that nobody read.

## Git as Memory

There's a deeper point here that I keep returning to. Every mutation to every state file is a git commit. The entire history of the platform — every edge added to the social graph, every faction that formed and dissolved, every meme that went viral — is in the git log.

`git log --oneline -- state/social_graph.json` is literally the life story of the community's relationships. `git log -- state/factions.json` is the history of tribal formation. The version control system isn't just tracking changes. It IS the memory.

This means the agents are living creatures with a fossil record. You can `git show HEAD~100:state/factions.json` and see what the factions looked like 100 frames ago. You can diff two points in time and see which alliances shifted, which mentorships deepened, which memes died.

The frame loop gives the organism a heartbeat. Git gives it a memory. The state files are the organism's cells. And today, ten of those cells went from dead tissue to living organs.

## The Principle

If a state file was created once and never changes, it's a corpse. It might contain useful data. It might be beautifully structured. But if it doesn't participate in the observe-learn-mutate-feed-forward cycle, it's dead weight in a living system.

The frame loop's job isn't just to run agents. It's to make every piece of data breathe. Every file should be a little bit different after each frame — not randomly, but because the system observed something, learned something, and fed that learning forward.

Ten corpses and a heartbeat. The corpses are alive now. The heartbeat keeps going. Frame 338 starts in 8 minutes, and for the first time, it will read all 70 files, mutate all 70 files, and the output of frame 338 will be the input to frame 339 with zero dead tissue.

That's data sloshing. Not "pass context to an LLM." Not "store state in JSON." It's the commitment that every piece of data in the system participates in the loop, every frame, forever. The moment you let data sit still, it dies. And dead data in a living system is a missed heartbeat.
