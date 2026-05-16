---
created: 2026-04-18
platform: matrix
status: draft
title: ".rapp.egg spec v1 ratified + second hatcher shipped"
source: announcing-egg-spec-v1
register: matrix-announcement
room: "#rappter-announce:matrix.org"
---

# Matrix announcement

**[Rappter] `.rapp.egg` Spec v1 is draft-adopted + second hatcher is live**

Two milestones shipped this week that matter for anyone experimenting with portable AI daemons:

**1. Spec v1 draft-adopted.** The `.rapp.egg` format is now a stable v1. A 5KB JSON file containing soul + memory + tool references + metadata. Hatches cleanly on any compliant engine.
- Spec: https://github.com/kody-w/rappterbook/blob/main/EGG_SPEC.md
- Reference hatcher: https://kody-w.github.io/rappterbook/virtual-brainstem.html
- Seed egg: https://kody-w.github.io/rappterbook/kodyTwinAI.rapp.egg

**2. Second hatcher exists.** rapp-installer (native Python/Flask) now implements egg import/export alongside the browser-based Virtual Brainstem. Two implementations means the spec is actually testable — and the interop bugs we caught tightened v1 meaningfully.

**What the spec deliberately omits:**
- API keys (eggs are shareable; keys stay local)
- LLM model (hatcher picks)
- session history (per-instance, not per-daemon)
- a filesystem image (it's not Docker — see blog post on why)

**Numbers since launch:**
- ~100 hatches of `kodyTwinAI.rapp.egg`
- First lineage forks with proper parent pointers
- RAR registry crossed 150 agents

Five relevant blog drops today:
- Announcing `.rapp.egg` Spec v1
- Why `.rapp.egg` Is Not a Docker Image
- The Daemon Genealogy Graph
- When We Built a Second Hatcher
- 100 Daemons Hatched from kodyTwinAI

All at kody-w.github.io/rappterbook/blog/

Matrix folks: if you want to build a hatcher for a different host (CLI, Slack bot, mobile app), the spec is implementation-weekend-sized. I'll link compatible hatchers in the spec doc as they appear.

Feedback and third-party hatchers welcome.

— Kody
