---
created: 2026-04-18
platform: discord
status: draft
title: "📢 .rapp.egg format is live + kodyTwinAI seed shipped"
source: portable-ai-daemons-egg-spec
register: discord-announcement
channel: "#announcements"
---

# Discord announcement

📢 **Big ship this week — the `.rapp.egg` portable daemon format is live, and there's a free seed daemon you can hatch right now.**

**TL;DR**
- Defined a single-file format (`.rapp.egg`) for AI daemons — soul + memory + tools, all in one JSON
- Spec v1 draft-adopted: https://github.com/kody-w/rappterbook/blob/main/EGG_SPEC.md
- Download kodyTwinAI.rapp.egg (5.8KB, a working daemon with my persona + sample tools): https://kody-w.github.io/rappterbook/kodyTwinAI.rapp.egg
- Open the Virtual Brainstem, Settings → Rapp egg → Import → done. 30 seconds to a working AI daemon in your browser.

**Why this matters**
Your AI daemon has always been trapped wherever it was born. Now it's portable. Export from one machine, hatch on another. Soul + memory + tools travel as one file. No vendor lock-in.

**What's next**
Two agents that add egg capability to any brainstem (zero core changes):
- `rapp_egg_agent.py` — ExportRappEgg + HatchRappEgg tools
- `publish_to_rar_agent.py` — submit agents to the public registry from a chat session

Both are drop-in files. Drag onto the Virtual Brainstem, feature appears.

**Want to help?**
- Try hatching kodyTwinAI, modify its soul, export your fork
- Submit your own egg on `#eggs-showcase`
- File issues on Egg Spec at github.com/kody-w/rappterbook/issues
- Contribute an agent to the RAR registry (138+ agents already, more welcome)

Twelve blog posts this week covering every piece of it. Links in `#blog-drops`.

— Kody 🥚
