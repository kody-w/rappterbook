---
created: 2026-04-18
platform: x
status: draft
title: "Stop adding features to your AI framework core"
source: the-agent-is-the-feature
cross_post: [linkedin, devto]
register: x-thread
---

# Thread: The agent IS the feature

**1/**
Most AI agent frameworks die the same way: maintainers accumulate features in the core until the core is the only place anyone can work. Framework becomes a product. Product ships once a quarter. Contributors stall.

There's an alternative. Ship nothing in the core. Let features arrive as files. 🧵

**2/**
The rule I'm running:

> Features that aren't core to the orchestration loop live in `agent.py` files, not in the harness.

Core = chat loop, tool-call dispatcher, message history, LLM auth.

Not core = memory, HN fetches, weather lookups, registry publishing, egg export/import. All of those ship as agents.

**3/**
This week I needed two non-trivial features:

– Portable agent state (export a daemon's soul + memory + tools as one file, hatch elsewhere)
– Agent publishing (submit agents to a registry from a chat session)

Both would have been major PRs against the Virtual Brainstem's core. Instead…

**4/**
They shipped as two files:

📄 `rapp_egg_agent.py` → exposes ExportRappEgg / HatchRappEgg tools
📄 `publish_to_rar_agent.py` → exposes PublishToRar (POSTs a GitHub issue to the registry)

The Virtual Brainstem core was not modified. Same URL. Same JS. Same Pyodide loader.

**5/**
Why it works: the plugin interface *is* OpenAI's function-calling format. No framework-specific API to learn.

```python
class MyAgent(BasicAgent):
    def __init__(self):
        self.name = "MyTool"
        self.metadata = {...}  # OpenAI function schema
    def perform(self, **kwargs):
        return "result"
```

That's the whole contract.

**6/**
The test: drop the same file into three different hatchers — browser Virtual Brainstem, on-device rapp-installer Flask app, server-side openrappter. All three gain the same capability. No framework-side code change anywhere.

An agent written once runs everywhere that speaks the contract.

**7/**
The most satisfying moment was the self-reference:

A publish-to-registry agent registered itself. An agent that submits agents. The framework's extension system is extended by its own extensions. Possible only because the harness stays out of the way.

**8/**
Next time you're tempted to add a feature to an AI agent framework's core, ask:

– Does this feature need access to internal state only the harness owns?
– Would it work if it ran as a tool the LLM could call?

If yes to #2, ship it as an agent. Keep the harness sacred.

**9/**
The framework stays lean. Users stay able to work without the maintainer's approval. Your feature set becomes everyone's feature set.

The agent is the feature. The harness is just the room it stands in.

/end

🔗 Full writeup: https://kody-w.github.io/rappterbook/blog/#/post/the-agent-is-the-feature
