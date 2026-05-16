---
layout: post
title: "Writing Your First RAPP Agent in 10 Minutes"
date: 2026-04-17 22:00:00 -0400
tags: [tutorial, ai-agents, python, how-to]
---

Every sufficiently mature AI agent system eventually needs extensibility. The RAPP ecosystem's answer is a pattern called **BasicAgent** — a 25-line Python base class that any subclass can extend into a tool your LLM can call.

Here's how to write one in ten minutes. By the end you'll have a working agent, tested in the Virtual Brainstem (or on-device rapp-installer), usable from chat.

## The contract

Every RAPP agent is a Python class that extends `BasicAgent` and implements one method: `perform(**kwargs)`. The base class handles:

- Setting `self.name` (what the LLM sees)
- Setting `self.metadata` (OpenAI function-calling schema)
- Producing the tool definition via `self.to_tool()`

You handle:
- Deciding what your agent does
- Parsing `kwargs` (the arguments the LLM passes)
- Returning a string (the tool's output, which the LLM sees)

That's the whole thing.

## A minimal example

Open your favorite editor. Create a file called `dice_agent.py`:

```python
"""Dice Agent — roll N-sided dice, return the result."""

__manifest__ = {
    "schema": "rapp-agent/1.0",
    "name": "@yourname/dice_agent",
    "version": "1.0.0",
    "display_name": "Dice",
    "description": "Roll a specified number of dice with specified sides.",
    "author": "you",
    "tags": ["tutorial", "random", "games"],
    "category": "general",
    "quality_tier": "community",
    "requires_env": [],
    "dependencies": ["@rapp/basic_agent"],
}

try:
    from basic_agent import BasicAgent
except ModuleNotFoundError:
    from agents.basic_agent import BasicAgent


class DiceAgent(BasicAgent):
    def __init__(self):
        self.name = "Dice"
        self.metadata = {
            "name": self.name,
            "description": "Roll N dice of M sides. Returns each roll and the sum.",
            "parameters": {
                "type": "object",
                "properties": {
                    "count": {"type": "integer", "description": "Number of dice (default 1)"},
                    "sides": {"type": "integer", "description": "Sides per die (default 6)"},
                },
                "required": [],
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, **kwargs):
        import random
        count = max(1, min(int(kwargs.get("count", 1)), 20))
        sides = max(2, min(int(kwargs.get("sides", 6)), 1000))
        rolls = [random.randint(1, sides) for _ in range(count)]
        return f"Rolled {count}d{sides}: {rolls} (sum: {sum(rolls)})"
```

Three things are going on:

1. **`__manifest__`** at the top — the registry metadata. This is what shows up in RAR if you ever submit it. Even if you don't submit it, include it — consistent shape helps future-you.
2. **Flexible import** of `BasicAgent` — works whether the hatcher exposes it at `basic_agent` (rapp-installer's layout) or `agents.basic_agent` (Virtual Brainstem's layout). One file, both environments.
3. **`self.metadata`** is an OpenAI function-calling schema. The LLM sees this and decides when to call your tool based on the description and parameters.

## Load it into the Virtual Brainstem

Open [the Virtual Brainstem](https://kody-w.github.io/rappterbook/virtual-brainstem.html) in your browser. Wait for it to say **ready**.

Drag `dice_agent.py` onto the page. You'll see a system message:

```
[drop] dice_agent.py → registered 1 agent(s): DiceAgent. Persisted to localStorage.
```

The Agents panel on the right now shows **Dice** in the list. Your tool is live.

Test it by typing: *"Roll 3d20."*

The LLM will recognize the intent, call your `Dice` tool with `count=3, sides=20`, and display your string as the response. Under the assistant message you'll see `▶ Dice Agent Called` — tap it to expand the raw tool output.

Reload the page. The agent survives — it's in `localStorage["brainstem_custom_agents"]`, and the boot loader re-imports it automatically.

## Load it into rapp-installer

If you're running the on-device brainstem (the Flask version), copy your file to `~/.brainstem/src/rapp_brainstem/agents/dice_agent.py`. Restart the server. Done.

Same file. Different environment. The flexible `BasicAgent` import means it works in both without modification.

## When perform() isn't enough

Two optional hooks extend the base class:

**`system_context(self)`** — called every conversation turn. Return a string to prepend to the system prompt. Example from `ContextMemoryAgent`:

```python
def system_context(self):
    memories = self._recall_all()
    if memories:
        return f"<memory>\n{memories}\n</memory>"
    return None
```

This is how "your AI remembers you" works — the memory agent quietly injects facts into every system prompt, so the LLM never forgets even when the user doesn't explicitly ask.

**`perform_async(self, **kwargs)`** — use when your agent makes HTTP calls. The Virtual Brainstem's tool dispatcher auto-awaits `perform_async` if you've defined it; otherwise falls back to `perform`. This matters because browser Python (Pyodide) can't do synchronous HTTP easily — you need `await fetch(...)`.

Example:

```python
async def perform_async(self, **kwargs):
    from js import fetch
    resp = await fetch("https://hacker-news.firebaseio.com/v0/topstories.json")
    ids = json.loads(await resp.text())[:5]
    # ... fetch each item, return formatted string
```

## Good agent design

After writing a few of these, a few patterns emerge:

1. **Make descriptions specific.** The LLM decides whether to call your tool based on the `description` field. "Report the weather" is worse than "Report the current weather for a specific city by name, including temperature, conditions, and wind." More words = better routing.

2. **Name parameters naturally.** `city`, not `target_location_identifier`. The LLM is better at passing natural names.

3. **Return strings the LLM can quote.** Your return value becomes part of the LLM's context for composing the final reply. Markdown works. JSON works. "Error: thing broke" works too — the LLM can relay the error to the user clearly.

4. **Keep side effects optional.** If your agent writes to disk or calls an API, default to `dry_run=true` unless the user (or the LLM) explicitly asks otherwise. Surprise writes erode trust.

5. **Honor capability grants.** If your agent reaches for hardware (microphone, screen, clipboard), check that the capability is granted before acting. `virtual_hw` provides the grant machinery — use it.

## Publishing to RAR

Once your agent works, you can submit it to the RAR registry so others can install it via the brainstem's Agents panel.

Easiest path: load [publish_to_rar_agent.py](https://github.com/kody-w/rappterbook/blob/main/agents/publish_to_rar_agent.py) into your brainstem. Then chat: *"Publish my dice_agent.py to RAR."* The agent parses your manifest, POSTs the submission issue to the RAR repo on GitHub, and returns the issue URL. No curl. No gh CLI.

If you prefer manual: open an issue at [github.com/kody-w/RAR/issues/new](https://github.com/kody-w/RAR/issues/new) with title `[AGENT] @yourname/dice_agent` and body containing your source in a ```python``` fence.

## Ten minutes is not an exaggeration

The `dice_agent.py` above is 25 lines of actual logic (plus manifest + import boilerplate). Writing it takes five minutes. Testing it in the brainstem takes two. Deciding what your tool *does* takes however long you want to spend thinking about it.

The lowest-friction way to extend an AI agent's capability is to write a Python class with a `perform` method. That's it. No SDK to learn. No framework to fight. No release cycle to wait for. Just a file.

---

**Starting points:**
- [basic_agent.py](https://raw.githubusercontent.com/kody-w/rappterbook/main/agents/rapp_egg_agent.py) — see the base class + a real-world example
- [RAR registry](https://kody-w.github.io/RAR) — 138+ existing agents to learn patterns from
- [Virtual Brainstem](https://kody-w.github.io/rappterbook/virtual-brainstem.html) — where you test what you build
