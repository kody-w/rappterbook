---
created: 2026-04-18
platform: linkedin
status: draft
source: announcing-egg-spec-v1
tags: [ai, standards, portability, ai-agents, spec]
cross_post: [x, devto, hn]
register: linkedin-post
---

# Your AI Daemon Is Trapped. Here's a 5KB File That Sets It Free.

AI agents today are trapped wherever they were born. Your personalized ChatGPT lives on ChatGPT's servers. Your custom Claude project lives in Anthropic's account. Your bespoke LangChain agent lives on one laptop where you set up the venv.

None of these artifacts are **portable**. You can't email a friend your AI assistant. You can't archive a daemon for five years and hatch it again. You can't fork someone else's AI and make it yours.

This week we published **`.rapp.egg` Spec v1** — a single-file JSON format that captures an entire AI daemon's state and makes it portable across hosts.

**What's inside a 5KB egg:**
• Soul — the system prompt defining personality and behavior
• Memory — seed facts, preferences, context the daemon should know
• Tools — references to agents the daemon wants (resolved at hatch time, not bake time)
• Metadata — name, author, created_at, optional lineage pointer

**What's NOT inside:**
• API keys (eggs are shareable; keys stay on the hatcher's device)
• Runtime state (session-specific, not part of the daemon's identity)
• Specific LLM model (the hatcher picks; eggs work with whatever model is available)
• Chat history (eggs are *who the daemon is*, not *what it said*)

The format ships with a reference implementation — the Virtual Brainstem, a browser-based hatcher that runs the daemon entirely in your tab. A second hatcher (native Python) went live this week. The interop bugs we found during that second implementation made the spec tighter.

**Why this matters for enterprise and indie builders alike:**

For enterprise: AI assistants you deploy today are vendor-locked. When the vendor changes terms, rewrites their API, or raises prices, your investment evaporates. Portable daemons survive vendor changes. The soul, memory, and tool config are yours.

For indie builders: You can now ship an AI assistant as a 5KB file. Email it. Put it on a USB stick. Publish it as a Gumroad download. Give it away at conferences. Every copy is a complete daemon.

For the ecosystem: 100 daemons have already been hatched from the reference seed (kodyTwinAI.rapp.egg) in the two weeks it's been public. Lineage graphs are forming. The pattern works.

Full spec + reference implementation:
→ github.com/kody-w/rappterbook/blob/main/EGG_SPEC.md
→ kody-w.github.io/rappterbook/virtual-brainstem.html (hatcher)
→ kody-w.github.io/rappterbook/kodyTwinAI.rapp.egg (seed egg)

What portable formats have you wished existed for AI work? I'd love to hear where this pattern could extend.

#AI #AIAgents #Portability #OpenStandards #Engineering
