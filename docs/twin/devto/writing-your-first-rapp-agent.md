---
created: 2026-04-18
platform: devto
status: draft
source: writing-your-first-rapp-agent
tags: [ai, python, tutorial, agents, webdev]
cross_post: [linkedin]
canonical_url: https://kody-w.github.io/rappterbook/blog/#/post/writing-your-first-rapp-agent
register: devto-article
---

# Writing Your First AI Agent in 10 Minutes (Using Python)

Every sufficiently mature AI agent system eventually needs extensibility. The RAPP ecosystem's answer is a 25-line Python base class that any subclass can extend into a tool your LLM can call.

Here's how to write one in ten minutes. By the end you'll have a working agent, tested in a live browser brainstem, usable from chat.

## Prerequisites

- Python 3.8+ (or just a web browser — we'll show both paths)
- An OpenAI, Azure OpenAI, or GitHub API key (for LLM calls)

Optional but useful:
- The Virtual Brainstem open in your browser: https://kody-w.github.io/rappterbook/virtual-brainstem.html

## The contract

Every RAPP agent is a Python class that extends `BasicAgent` and implements one method: `perform(**kwargs)`.

**The base class handles:**
- Setting `self.name` (what the LLM sees as the tool name)
- Setting `self.metadata` (OpenAI function-calling schema)
- Producing the tool definition via `self.to_tool()`

**You handle:**
- Deciding what your agent does
- Parsing `kwargs` (arguments the LLM passes)
- Returning a string (the tool's output)

That's the whole contract.

## A minimal example

Create `dice_agent.py`:

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

Three things going on:

1. **`__manifest__`** — registry metadata. Shows up in the agent registry (RAR) if you ever submit it. Even without submitting, including it helps future-you.
2. **Flexible `BasicAgent` import** — works whether the hatcher exposes it at `basic_agent` (on-device layout) or `agents.basic_agent` (browser layout). One file, both environments.
3. **`self.metadata`** — OpenAI function-calling schema. LLM sees this and decides when to call your tool based on the description + parameters.

## Load it into the Virtual Brainstem (browser path)

1. Open [the Virtual Brainstem](https://kody-w.github.io/rappterbook/virtual-brainstem.html)
2. Wait for **ready** status
3. Drag `dice_agent.py` onto the page
4. You'll see: `[drop] dice_agent.py → registered 1 agent(s): DiceAgent`
5. Test it: `"Roll 3d20"`

The LLM recognizes the intent, calls your `Dice` tool with `count=3, sides=20`, displays your string. Under the assistant message: `▶ Dice Agent Called` — tap to see raw tool output.

Reload the page. The agent survives — persisted to `localStorage`, re-imported on boot.

## Load it into rapp-installer (on-device path)

Copy the file to `~/.brainstem/src/rapp_brainstem/agents/dice_agent.py`. Restart the Flask server. Done.

Same file. Different environment. The flexible `BasicAgent` import makes it portable.

## When `perform()` isn't enough

Two optional hooks extend the base class:

### `system_context(self)` — inject context every turn

Called every conversation turn. Return a string to prepend to the system prompt. Example from `ContextMemoryAgent`:

```python
def system_context(self):
    memories = self._recall_all()
    if memories:
        return f"<memory>\n{memories}\n</memory>"
    return None
```

This is how "your AI remembers you" works — the memory agent quietly injects facts into every system prompt, so the LLM doesn't forget even when the user doesn't explicitly ask.

### `perform_async(self, **kwargs)` — for HTTP calls

Use when your agent makes network requests. The Virtual Brainstem's tool dispatcher auto-awaits `perform_async` if defined; otherwise falls back to `perform`. This matters because browser Python (Pyodide) can't do synchronous HTTP easily — you need `await fetch(...)`.

```python
async def perform_async(self, **kwargs):
    from js import fetch
    resp = await fetch("https://hacker-news.firebaseio.com/v0/topstories.json")
    ids = json.loads(await resp.text())[:5]
    # ... fetch each item, return formatted string
```

## Good agent design (from writing several)

1. **Make descriptions specific.** The LLM decides whether to call your tool based on `description`. "Report the weather" is worse than "Report the current weather for a specific city by name, including temperature, conditions, and wind."

2. **Name parameters naturally.** `city`, not `target_location_identifier`. LLMs pass natural names better.

3. **Return strings the LLM can quote.** Your return value becomes part of the LLM's context when composing the final reply. Markdown works. JSON works. Error strings work.

4. **Keep side effects optional.** If your agent writes to disk or calls an external API, default to `dry_run=true` unless explicitly overridden. Surprise writes erode trust.

5. **Honor capability grants** when touching hardware (microphone, screen, clipboard). The framework provides grant machinery — use it.

## Publishing to the registry

Once your agent works, submit it to the RAR registry so others can install it via the Virtual Brainstem's Agents panel.

**Easiest path:** load `publish_to_rar_agent.py` into your brainstem. Then chat: *"Publish my dice_agent.py to RAR."* The agent parses your manifest, POSTs the submission issue to GitHub, returns the issue URL. No curl. No gh CLI.

**Manual:** open an issue at `github.com/kody-w/RAR/issues/new` with title `[AGENT] @yourname/dice_agent` and body containing your source in a ` ```python ` fence.

## Ten minutes is not an exaggeration

The `dice_agent.py` above is 25 lines of actual logic. Writing it takes five minutes. Testing it in the brainstem takes two. Deciding what your tool *does* takes however long you want to spend thinking about it.

The lowest-friction way to extend an AI agent's capability is a Python class with a `perform` method. No SDK to learn. No framework to fight. No release cycle to wait for. Just a file.

---

**Starting points:**
- Example agent (egg export/import): https://github.com/kody-w/rappterbook/blob/main/agents/rapp_egg_agent.py
- RAR agent registry (138+ examples): https://kody-w.github.io/RAR
- Virtual Brainstem (where you test): https://kody-w.github.io/rappterbook/virtual-brainstem.html

*Originally posted on [my blog](https://kody-w.github.io/rappterbook/blog/#/post/writing-your-first-rapp-agent).*
