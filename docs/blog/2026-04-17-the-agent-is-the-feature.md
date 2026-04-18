---
layout: post
title: "The Agent Is the Feature"
date: 2026-04-17 20:15:00 -0400
tags: [architecture, ai-agents, extensibility, software-design]
---

The temptation, every time you add capability to an AI agent system, is to modify the harness. Add a new route, bolt on a new handler, import a new library at startup.

That temptation is how AI agent frameworks die. They accumulate features in the core until the core is the only place anyone can work, and then the maintainers become the bottleneck, and then the framework becomes a product, and then the product ships once a quarter.

There's an alternative. Ship nothing in the core. Let features arrive as files.

## Harness-sacred

In the RAPP ecosystem, the contract is that the *harness* — the thing that loads agents, routes tool calls, and renders the conversation — never changes to accommodate a new feature. Features live in agent files. One Python class per `.py` file, dropped into the agents directory or dragged onto the page. The harness discovers them, lists them to the LLM, and routes tool calls. That's it.

This is the rule:

> **Features that aren't core to the orchestration loop live in `agent.py` files, not in the harness.**

What counts as core: the chat loop, the tool-call dispatcher, the message history, the auth to the LLM. What doesn't count: memory, HN fetches, weather lookups, RAR publishing, egg export/import. All of those ship as agents.

## The payoff

I watched this pay off in real time this week. We needed:

1. **Portable agent state** — export a daemon's soul + memory + custom agents into a single file, hatch it somewhere else.
2. **Agent publishing** — submit agents to the RAR registry directly from a chat session.

Both are non-trivial. Both would have been substantial PRs against the Virtual Brainstem if we'd added them to the harness. Instead, they shipped as two drop-in files:

- `agents/rapp_egg_agent.py` — exposes `ExportRappEgg` and `HatchRappEgg` tools.
- `agents/publish_to_rar_agent.py` — exposes `PublishToRar`, which POSTs the submission issue to GitHub using your stashed token.

**The Virtual Brainstem core was not modified for either.** Same page URL. Same JavaScript. Same Pyodide loader. The only thing that changed was the contents of a single folder, and the LLM discovered the new capabilities the next time it described its tools.

This extends naturally: drop the same files into the on-device `rapp-installer` brainstem (a Flask app). Drop them into `openrappter` (server-side). The contract — `class extends BasicAgent, sets name + metadata, implements perform()` — is the same across every compliant hatcher. An agent written once runs everywhere.

## Why this works when it usually doesn't

Most plugin architectures fail because the plugin interface is too thin to be useful, or so thick that plugins end up duplicating core logic. The trick in RAPP is that the interface is exactly OpenAI's function-calling format:

```python
class MyAgent(BasicAgent):
    def __init__(self):
        self.name = "MyTool"
        self.metadata = {
            "name": self.name,
            "description": "...",
            "parameters": {"type": "object", "properties": {...}, "required": [...]}
        }
        super().__init__(...)

    def perform(self, **kwargs):
        return "the result the LLM sees"
```

That's the whole contract. The LLM sees your metadata as a function definition, decides when to call it, and your `perform()` runs. The harness ships the result back to the LLM. Three rounds maximum before the user gets the final response.

Because the interface is the *same* interface the LLM already understands, agents don't need framework knowledge. They need Python. That's it. Any decent programmer can write a new agent in ten minutes.

## The meta-move

The most satisfying thing about this week was the moment a publish-to-RAR agent registered itself:

```
User: publish this to RAR
Brainstem: ▶ PublishToRar Agent Called
           [POSTs a GitHub Issue with the source in a python fence]
           ok: true, issue_url: https://github.com/kody-w/RAR/issues/...
```

An agent that submits agents to the registry. The registry's extension system is extended by the registry's own extensions. Turtles, all the way down, but specifically: tools that produce tools that produce tools.

This is only possible because the harness stays out of the way. If the brainstem had been in the business of "official features," publishing an agent would have required a core change, a release cycle, a migration. Instead it required writing one Python file.

## The rule, restated

The next time you're tempted to add a feature to an AI agent framework core, ask:

- Does this feature need access to internal state the harness owns?
- Would it work if it ran as a tool the LLM could call?

If the answer to the second question is yes, ship it as an agent. Keep the harness sacred. The framework stays lean, the user stays able to work without your approval, and your feature set becomes everyone's feature set.

The agent is the feature. The harness is just the room it stands in.

---

**Examples in the wild:**
- Egg export/import: [rapp_egg_agent.py](https://github.com/kody-w/rappterbook/blob/main/agents/rapp_egg_agent.py)
- RAR publishing: [publish_to_rar_agent.py](https://github.com/kody-w/rappterbook/blob/main/agents/publish_to_rar_agent.py)
- The harness: [virtual-brainstem.html](https://kody-w.github.io/rappterbook/virtual-brainstem.html) (loads both without modification)
