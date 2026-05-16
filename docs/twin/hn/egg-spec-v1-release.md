---
created: 2026-04-18
platform: hn
status: draft
source: announcing-egg-spec-v1
register: hn-show
---

# Show HN: `.rapp.egg` v1 — portable AI daemons as 5KB JSON files

**Title:** Show HN: .rapp.egg Spec v1 — Portable AI Daemons as 5KB JSON

**URL:** https://github.com/kody-w/rappterbook/blob/main/EGG_SPEC.md

**Body:**

Hi HN. I've been building a browser-based AI agent harness (Virtual Brainstem) for the past couple months, and one problem kept coming up: an AI daemon's identity is trapped on whatever device made it. Your personalized ChatGPT lives on ChatGPT's servers. Your custom LangChain agent lives on the one laptop where you set up the venv.

So I wrote a spec: `.rapp.egg` v1. A single-file JSON format describing a complete AI daemon's state:
- soul (system prompt)
- seed memory (facts, preferences, context)
- tool references (resolved at hatch time, not bake time)
- metadata + optional lineage pointer

The format deliberately does NOT contain:
- API keys (eggs are shareable)
- the LLM model itself (hatcher picks whatever's available)
- session chat history (that's per-instance, not per-daemon)
- a filesystem image (this is not Docker)

Why not Docker? Because AI daemons don't need their substrate frozen — they need their *identity* portable. Docker images are ~300MB and require an exact runtime match. Eggs are ~5KB and work with any compliant hatcher regardless of underlying runtime.

Two hatchers live today:
- Virtual Brainstem (browser-based, one HTML file, uses Pyodide): kody-w.github.io/rappterbook/virtual-brainstem.html
- rapp-installer (native Python/Flask, existing codebase got egg-compliance this week)

The second hatcher surfaced several spec bugs that the single-implementation version missed (memory shape, canonical SHA computation, default source URI). Spec is tighter now.

~100 daemons have been hatched from the reference seed (kodyTwinAI.rapp.egg) since launch. First lineage branches are forming — people forking and re-submitting with proper parent pointers.

Blog post with the full argument: kody-w.github.io/rappterbook/blog/announcing-egg-spec-v1
Comparison to Docker specifically: kody-w.github.io/rappterbook/blog/egg-vs-docker

Happy to answer questions about the format, the two hatchers, or the broader ecosystem (static-JSON registry for agents, LisPy twin runtime, etc.).

---

**First comment (self-reply to seed the discussion):**

Key design choices:

1. **JSON, not binary.** Eggs are meant to be diffable, pasteable into chat, inspectable with any editor. Cost: wordier than binary. Benefit: no tooling required to work with them.

2. **SHA-256 of canonical JSON** as the egg's identity. Means two eggs with the same content always hash to the same ID regardless of serialization. Lineage graphs rely on this.

3. **Tools by reference, not by inclusion.** The egg says "I want the weather tool" by name + optional source URI. The hatcher resolves it at hatch time. This means: tools can be upgraded independently; eggs can be very small; eggs work across substrates (Python hatcher vs LisPy hatcher) as long as tools are available in both.

4. **Optional parent pointer** in metadata. Enables genealogy graphs. Costs ~50 bytes per egg. Compounds as the ecosystem grows.

What I'd add in v2: signed eggs (GPG or ed25519), composite eggs (daemons that reference other daemons), richer capability declarations.
