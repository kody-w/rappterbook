---
created: 2026-04-18
platform: hn
status: draft
title: "Show HN: Virtual Brainstem — zero-install AI chat with portable daemons"
source: flask-app-in-a-browser-tab
register: hn-show
---

# Show HN: Virtual Brainstem — zero-install AI chat with portable memory, pluggable agents, and a single-file daemon format

https://kody-w.github.io/rappterbook/virtual-brainstem.html

I built this over the last couple weekends and am finally ready to show it.

**The short version:** an AI chat app that runs entirely in a browser tab. You bring your own OpenAI, Azure OpenAI, or GitHub API key (stashed in localStorage on your device, never transmitted anywhere else). It has persistent memory that survives reloads. You can extend it by dragging Python "agent" files onto the page. It works on iPhone Safari.

**The longer version:** I had a 1,500-line Flask app called the RAPP brainstem that runs on `localhost:7071` and does OpenAI-style tool calling with agent auto-discovery. This week I deleted the server part using Pyodide. The app still works. Same Python modules, same agent-loading logic, same tool-calling loop — just running client-side in WASM instead of Python on your laptop.

**What you can do with it:**

- Basic chat against any OpenAI-compatible endpoint (OpenAI proper, Azure OpenAI, GitHub Models)
- Persistent memory — tell it facts, reload the tab tomorrow, it remembers (localStorage + a `ContextMemory` agent that auto-injects stored facts into the system prompt)
- Custom tools — drag any Python file implementing a `BasicAgent` subclass onto the page. LLM sees it as a new function immediately.
- Browse an agent registry (RAR) with 138+ community tools, one-click install each
- Export the daemon's complete state (soul + memory + installed tools) as a single `.rapp.egg` JSON file, portable to any compliant hatcher

**What's genuinely new (I think):**

- **Single-file AI daemon format** — the `.rapp.egg` spec (draft v1) captures a daemon's entire state in one JSON file with SHA-verified integrity and lineage tracking. Hatch it on any compliant engine and the daemon resumes exactly where it left off. Think Docker image but for AI personalities + memory + tools.
- **Static-JSON package registry** — the RAR agent registry at github.com/kody-w/RAR is just `registry.json` + `agents/@publisher/slug.py` files on GitHub. No server. Submissions happen via GitHub Issues. Reads require no auth. Mirroring is `git clone`.
- **Harness-sacred architecture** — features don't go in the core, they ship as agent files. The egg export/import is an agent. The registry submission is an agent. Same file drops into a browser OR an on-device Flask app OR a server runtime, and the capability appears everywhere.

**Trade-offs I'm aware of:**

- First boot downloads ~10MB of Pyodide. Cached afterward but slow the first time.
- iOS Safari caps the WebAssembly heap aggressively. Big workloads (real numpy arrays, etc.) don't fit — most chat use cases don't care.
- There's no sync across devices built in. Each device has its own localStorage. You can export/import `.rapp.egg` files to move state manually.

**Code / specs:**

- Virtual Brainstem source (single HTML file): https://github.com/kody-w/rappterbook/blob/main/docs/virtual-brainstem.html
- LisPy (the zero-dep Python digital twin that sits under the browser Python runtime): https://github.com/kody-w/rappterbook/blob/main/dist/lispy.py
- Egg Spec v1: https://github.com/kody-w/rappterbook/blob/main/EGG_SPEC.md
- RAR registry: https://kody-w.github.io/RAR
- Writeup — "A Flask App That Lives in a Browser Tab": https://kody-w.github.io/rappterbook/blog/#/post/flask-app-in-a-browser-tab

**What would most help me right now:** honest reactions to the "harness sacred, features ship as agent files" extensibility pattern. It's the thing I'm most curious whether other people will find useful. If you've built an AI agent framework and felt the "core keeps accumulating features" pressure, I'd love to compare notes.

Happy to answer questions about any of it.
