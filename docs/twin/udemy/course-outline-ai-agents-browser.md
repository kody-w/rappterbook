---
created: 2026-04-18
platform: udemy
status: draft
title: "AI Agents in the Browser: Build, Extend, and Distribute Your Own AI Daemon"
source: writing-your-first-rapp-agent
register: udemy-course
target_length: "4-5 hours, ~35 lessons"
audience: "Intermediate Python developers curious about AI agents; no prior AI-framework experience required"
---

# Udemy course outline: "AI Agents in the Browser"

## Course description

Build AI agents that run entirely in your browser, use your own API key, remember users across sessions, and extend infinitely via drop-in Python files. No servers. No accounts. No subscriptions. Ship production-capable agents in an afternoon.

## What students will learn

- Architecture of modern AI agent systems (OpenAI function-calling + tool-use loops)
- The "BasicAgent" pattern — how to write agents as single Python files
- Persistent memory in the browser via localStorage (the `ManageMemory` / `ContextMemory` pattern)
- Integrating hardware access (screenshot, microphone, notifications) via browser Web APIs
- Portable daemon state — the `.rapp.egg` spec for moving AI personalities between machines
- Publishing agents to a public registry (RAR)
- Running the same code on-device (Flask) and in-browser (Pyodide) without modification

## Prerequisites

- Comfortable with Python (functions, classes, kwargs)
- Basic JavaScript + HTML familiarity
- An OpenAI, Azure OpenAI, or GitHub API key (for labs)

## Section outline

### Section 1 — Orientation (25 min)

1. *Welcome + course structure* (5 min)
2. *What is an "AI daemon"?* (5 min)
3. *The hatcher/daemon distinction* — organism vs engine (5 min)
4. *Getting your API key — 3 provider walkthroughs* (10 min)

### Section 2 — Your First Agent (50 min)

1. *Open the Virtual Brainstem — orientation* (5 min)
2. *Anatomy of the `BasicAgent` class* (10 min)
3. *Lab: Write a Dice agent* (20 min) — live-code a full agent with manifest, metadata, perform()
4. *Drag-drop deployment* (5 min)
5. *Testing the LLM's tool-routing* (10 min) — what makes a good description, how to debug misroutes

### Section 3 — Memory and Personalization (40 min)

1. *The `ManageMemory` + `ContextMemory` pair* (10 min)
2. *`system_context()` — injecting state into the system prompt* (10 min)
3. *Lab: Persistent task tracker agent* (15 min) — students build an agent that remembers todos across sessions
4. *Privacy model — why localStorage beats cloud memory* (5 min)

### Section 4 — Tools That Talk to the World (50 min)

1. *`perform_async` — async tool calls* (10 min)
2. *HTTP in the browser via js.fetch* (10 min)
3. *Lab: Weather agent with a real API* (20 min) — students integrate a real weather API
4. *Hardware agents — screenshot, mic, clipboard, notifications* (10 min)

### Section 5 — The Digital Twin Stack (40 min)

1. *LisPy — Python's digital twin runtime* (10 min)
2. *virtual_pip — package ecosystem as a registry of shims* (10 min)
3. *virtual_os — OS API twinning* (10 min)
4. *virtual_hw — hardware bridge with capability grants* (10 min)

### Section 6 — Portability (`.rapp.egg`) (35 min)

1. *What's in an egg* (10 min)
2. *Lab: Export + re-hatch* (15 min) — students export their daemon, hatch on a different browser, verify state
3. *Lineage + provenance* (10 min)

### Section 7 — The RAR Registry (30 min)

1. *Browsing + installing community agents* (10 min)
2. *Lab: Publish your first agent* (15 min) — student uses `publish_to_rar_agent` to submit their dice agent
3. *What happens after submission — the review process* (5 min)

### Section 8 — The Harness-Sacred Architecture (30 min)

1. *Why features should ship as agents, not framework additions* (10 min)
2. *Contrast: the RAPP pattern vs. plugin systems that fail* (10 min)
3. *Lab: Extend rapp-installer with your agent* (10 min) — student runs the on-device Flask version, drops their agent in, demonstrates the same file works in two substrates

### Section 9 — Production Considerations (25 min)

1. *Mobile (iOS Safari specifics)* (10 min)
2. *Key management + rotation* (5 min)
3. *Rate limits + cost monitoring* (5 min)
4. *When to move from brainstem (forge) to hippocampus (theatre)* (5 min)

### Section 10 — Capstone (45 min)

1. *Design brief — build a "personal assistant" daemon* (5 min)
2. *Lab: Capstone build* (35 min) — students combine soul-editing, custom agents (calendar, email drafts, reminder persistence), and export as a shareable egg
3. *Showcase + peer review* (5 min)

## Price + positioning

**Free intro course** (sections 1-2): build-and-run in 30 min, available on YouTube.
**Paid full course** ($29 launch, $49 standard): sections 3-10, with downloadable code + egg seeds per section.

Positioned against Coursera's "Build AI Agents with LangChain" type courses — differentiated by:
- Zero install required (runs in browser)
- Zero framework to learn (just Python + OpenAI schema)
- Zero vendor lock-in (your key, your memory, your egg)
- Production pattern built for distribution, not a tutorial toy

## Deliverables students walk away with

- A working AI daemon (their own) hosted nowhere but their device
- At least 3 custom agents they wrote
- A published agent in the RAR registry
- A `.rapp.egg` of their daemon, portable to any hatcher
- Understanding of the agent-framework design patterns that let them build more

## Companion materials

- Downloadable code for every lab (GitHub repo with one branch per section)
- Starter `.rapp.egg` seeds they can fork
- Discord channel for student Q&A (community-supported)
- Free "Advanced Topics" supplement covering the hippocampus when that ships

---

**First recording notes:**
- Screen-record Safari on macOS (matches the iOS experience closely)
- Keep code font size comfortable for laptop screens (14pt+)
- Show the agent-call output panel prominently in every lab — the "▶ Agent Called" collapsible is the course's signature visual
