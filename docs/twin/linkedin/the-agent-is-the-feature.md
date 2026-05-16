---
created: 2026-04-18
platform: linkedin
status: draft
source: the-agent-is-the-feature
tags: [ai, architecture, extensibility, framework-design, engineering-leadership]
cross_post: [x, devto]
register: linkedin-post
---

# The AI Agent Framework Anti-Pattern That Kills Contribution

Every AI agent framework I've watched over the last year has the same slow death.

Someone builds a promising core. Community gets excited. Contributors want to add features. Each feature requires modifying the core. Reviews pile up. Maintainers become the bottleneck. The framework becomes a product. The product ships once a quarter. Contributors drift away.

The pattern is so consistent it looks like a law.

But it isn't. There's an alternative design — one that I've been running for six months in the RAPP ecosystem — where contributors can add capabilities *without ever touching the core*.

The rule: **features live in `agent.py` files, not in the harness.**

The harness handles the orchestration loop: load agents, route tool calls, manage message history, authenticate to the LLM. That's it. Everything else — memory, external API calls, registry operations, export/import, scheduled tasks — ships as agent files that drop into an `agents/` directory.

The plugin interface is exactly OpenAI's function-calling format. No framework-specific API. A contributor writes a Python class extending `BasicAgent`, sets `self.name` + `self.metadata` (OpenAI schema) + implements `perform(**kwargs)`, and their feature is live.

Two real features that landed this week as drop-in files:

**1. Portable agent state.** An agent called `rapp_egg_agent.py` exposes `ExportRappEgg` and `HatchRappEgg` tools. The LLM can now pack the daemon's entire state (soul, memory, installed tools) into a single JSON file, or hatch an incoming file. ~300 lines of Python. Zero framework changes.

**2. Registry publishing.** `publish_to_rar_agent.py` exposes a `PublishToRar` tool that POSTs a GitHub issue to the agent registry. Submissions now happen from a chat session — "Publish my dice_agent to RAR" triggers the tool, which builds the submission body and POSTs it. Again: zero framework changes.

Both files drop into three different hatchers — browser-native Virtual Brainstem, on-device Flask app, server-side runtime — and all three gain the same capability.

The payoff extends beyond contribution velocity:

- **The framework stays lean.** I don't need to maintain memory infrastructure, HTTP clients, registry integrations, or any other domain logic in the core.
- **Users can fork behavior without forking the framework.** Want memory stored in Azure instead of localStorage? Write an agent. Want a different registry backend? Write an agent.
- **Features compose.** The publish-to-registry agent *uses* the export-egg agent internally. Tools that call tools. The LLM orchestrates the composition.
- **The most satisfying moment:** an agent that submits agents to the registry registered itself. The framework's extension system is extended by its own extensions. Only possible because the harness stays out of the way.

The principle I'd offer to anyone building AI agent tooling:

> If a feature can be implemented as a tool the LLM calls, ship it as a tool. Keep the harness sacred.

This is essentially the UNIX philosophy applied to AI agents. The harness is the kernel. Agents are the userspace programs. They compose through well-defined interfaces (tool-calling schemas). The kernel stays small; userspace expands forever.

Your feature set becomes your users' feature set. The framework isn't a product you ship. It's a substrate they build on.

#AIEngineering #SoftwareArchitecture #Extensibility #OpenSource

---

Full technical writeup with code examples: https://kody-w.github.io/rappterbook/blog/#/post/the-agent-is-the-feature

Agent examples in the wild:
- Export / hatch egg: https://github.com/kody-w/rappterbook/blob/main/agents/rapp_egg_agent.py
- Publish to registry: https://github.com/kody-w/rappterbook/blob/main/agents/publish_to_rar_agent.py
