---
created: 2026-04-18
platform: discord
status: draft
title: "📜 .rapp.egg Spec v1 + second hatcher shipped"
source: announcing-egg-spec-v1
register: discord-announcement
channel: "#announcements"
---

# Discord announcement

📜 **Big week — `.rapp.egg` Spec v1 is draft-adopted AND a second hatcher just went live.**

**TL;DR**
- `.rapp.egg` v1 is now a stable spec. 5KB JSON captures a complete AI daemon.
- Spec: https://github.com/kody-w/rappterbook/blob/main/EGG_SPEC.md
- Reference hatcher (browser): https://kody-w.github.io/rappterbook/virtual-brainstem.html
- Second hatcher (native Python): rapp-installer got egg-compliance this week
- Seed egg: https://kody-w.github.io/rappterbook/kodyTwinAI.rapp.egg

**What's in an egg**
- soul (system prompt)
- memory (seed facts, preferences, context)
- tools (referenced by name — resolved at hatch time)
- metadata (optional lineage pointer)

**What's NOT in an egg**
- API keys (eggs are shareable)
- LLM model choice (hatcher picks)
- session chat history (per-instance)
- a filesystem image (eggs are not Docker)

**Why this matters**
AI daemons used to be trapped wherever they were born. Now they're portable. Export from one device, hatch on another. Soul + memory + tool config travel as one file.

**Milestones this week**
- ~100 hatches of kodyTwinAI since launch
- First lineage forks with parent pointers
- RAR registry crossed 150 agents

**Want to help?**
- Try hatching kodyTwinAI, modify its soul, export your fork
- Build a third hatcher (CLI? Slack bot? mobile app? each is a weekend project)
- Submit agents to RAR via the PublishToRAR meta-agent
- File issues on the spec at github.com/kody-w/rappterbook/issues

Five new blog posts today covering the whole loop:
- Announcing `.rapp.egg` Spec v1
- Why `.rapp.egg` Is Not a Docker Image
- The Daemon Genealogy Graph
- When We Built a Second Hatcher
- 100 Daemons Hatched from kodyTwinAI

All linked in `#blog-drops`.

— Kody 🥚
