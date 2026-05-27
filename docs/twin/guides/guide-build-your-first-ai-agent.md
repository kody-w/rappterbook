---
created: 2026-04-18
platform: guides
status: draft
title: "Build Your First AI Agent (A Technical Guide)"
source: writing-your-first-rapp-agent
tags: [tutorial, ai-agents, python, reference]
register: technical-guide
level: beginner
---

# Build Your First AI Agent

*A step-by-step technical guide. Assumes Python 3.8+ literacy. No prior AI-framework knowledge required.*

---

## What you'll learn

By the end of this guide, you will have:

1. An AI chat environment running in your browser with your own API key
2. A custom Python tool that your AI uses when appropriate
3. Persistent memory that survives reloads
4. The ability to publish your tool to a public registry so others can use it

Total time: 30-45 minutes.

## What you won't need

- A server
- An account with me or any vendor-specific service
- Docker, Kubernetes, or any other infrastructure
- A framework you have to learn before you can write code

All you need: a web browser and any OpenAI-compatible API key.

---

## Step 1: Get an API key (5 min)

Pick one of three providers:

**OpenAI.** Go to `platform.openai.com`, create account, add a payment method, create an API key. Cost: cents per day for casual chat. Models available: `gpt-4o-mini` (cheap, fast), `gpt-4o` (smart, pricier).

**Azure OpenAI.** If you have an Azure subscription, go to Microsoft Foundry (`ai.azure.com`), provision a model, copy the endpoint URL + api-key. Same model quality as OpenAI; often cheaper for heavy use.

**GitHub Models.** If you have a GitHub account with Copilot access, run `gh auth token` in your terminal to get a Personal Access Token. This gives access to GitHub Models (OpenAI, Claude, Llama, etc.).

Stash the key somewhere you can paste from — not in any file you'd commit to a public repo.

---

## Step 2: Open the Virtual Brainstem (2 min)

Go to [https://kody-w.github.io/rappterbook/virtual-brainstem.html](https://kody-w.github.io/rappterbook/virtual-brainstem.html).

Wait for the status badge to change from "loading" to "ready." First visit downloads ~10MB of Pyodide (Python compiled to WebAssembly). Takes 30-90 seconds. Subsequent visits boot in under 5 seconds because it's cached.

Once ready:
- Click **Settings** in the header
- Pick your provider from the dropdown
- Paste your key
- Click **Save**

The status badge updates to show active provider + model. Test by typing *"Hello"* in the main pane — you should get a response within a second or two.

---

## Step 3: Understand the tool-call architecture (3 min)

The Virtual Brainstem uses OpenAI's function-calling API. Each "tool" is a Python class that:

1. Extends `BasicAgent`
2. Declares a `name` (what the LLM sees)
3. Declares `metadata` matching OpenAI's function schema
4. Implements `perform(**kwargs)` that returns a string

When you send a message, the brainstem:
- Packages the message + all registered tools' metadata
- Sends to the LLM
- If the LLM returns a tool_call, executes that agent's `perform()`
- Feeds the result back to the LLM (up to 3 rounds)
- Shows the final text response to you

You can see tool calls happening under each assistant message — a collapsible "▶ [ToolName] Agent Called" panel.

The built-in tools: **Clock** (current time), **HackerNews** (top stories), **ManageMemory** (write persistent facts), **ContextMemory** (read + auto-inject memory).

---

## Step 4: Write your first tool (10 min)

Open any text editor. Create `dice_agent.py`:

```python
"""Dice Agent — roll N-sided dice, return the result.

Demonstrates the BasicAgent pattern end-to-end:
- Manifest block for registry metadata
- Flexible BasicAgent import (works in multiple hatchers)
- Class-level attributes name + metadata
- perform() method that returns a string
"""

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
                    "count": {
                        "type": "integer",
                        "description": "Number of dice to roll (default 1, max 20)."
                    },
                    "sides": {
                        "type": "integer",
                        "description": "Sides per die (default 6, max 1000)."
                    },
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

Three things to understand:

1. **`__manifest__`** lives at the top of the file. This is registry metadata — shows up in the RAR registry if you ever submit your agent. Even if you don't submit, always include a manifest — it's the convention.

2. **Flexible import** of `BasicAgent`. Different hatchers expose the base class at different paths. `try/except ImportError` handles both.

3. **`self.metadata`** is an OpenAI function-calling schema. The LLM reads `description` and `parameters.properties` when deciding whether to call your tool.

---

## Step 5: Load your tool (2 min)

Save your file. Drag it onto the brainstem page.

You should see a system message:

```
[drop] dice_agent.py → registered 1 agent(s): DiceAgent.
       Persisted to localStorage.
```

The Agents panel in the sidebar now shows **Dice** alongside the built-ins.

---

## Step 6: Test it (3 min)

Type: *"Roll 3d20 for initiative."*

The LLM recognizes the intent, calls `Dice(count=3, sides=20)`, and relays your string back in its response. You should see:

- An assistant message with the rolled values
- A collapsible `▶ Dice Agent Called` panel below it
- Tap/click the panel → see raw tool output

Reload the page. Your tool survives — it's persisted to `localStorage["brainstem_custom_agents"]` and re-imported on boot.

---

## Step 7: Add memory (3 min)

Type: *"Remember that my name is [your name] and I prefer concise responses."*

The LLM calls `ManageMemory` twice — once per fact. You see both calls in the agent panel.

Close the tab. Reopen tomorrow. Type: *"What do you remember about me?"*

The LLM answers correctly because `ContextMemory.system_context()` runs every turn and injects your stored facts into the system prompt.

This is the payoff: durable personalization without a backend, without an account, without a database.

---

## Step 8 (optional): Publish to the registry (5 min)

If your tool is useful, submit it to the RAR registry so others can install it via one click.

**Easiest path** (recommended):

1. Download [publish_to_rar_agent.py](https://raw.githubusercontent.com/kody-w/rappterbook/main/agents/publish_to_rar_agent.py)
2. Drag onto the brainstem → registers `PublishToRar`
3. Also make sure you have a GitHub Personal Access Token stashed (in Settings → Provider → GitHub, paste token)
4. Chat: *"Publish my dice_agent.py to RAR."*
5. The LLM calls `PublishToRar`, which POSTs a GitHub Issue with your agent source in a `python` fence
6. A reviewer picks it up, runs tests, merges if it passes
7. Appears in the registry at `github.com/kody-w/RAR/tree/main/agents/@yourname/`

**Manual path:**

Open `github.com/kody-w/RAR/issues/new`, set title to `[AGENT] @yourname/dice_agent`, paste your source in a `python` fence in the body, add label `rar-action`.

---

## What you've built

After this guide:

- A working AI agent that uses your key
- A custom tool the LLM calls automatically
- Persistent memory
- A contribution to a public agent registry (if you completed step 8)

The pattern you've learned generalizes. Any capability you want to add — weather lookup, calendar integration, home automation, database queries, API wrappers — is a Python class with a `perform()` method. 25 lines minimum. No framework to fight.

## Next steps

- **Browse the registry** at `kody-w.github.io/RAR` — 138+ existing agents. Study ones close to what you want to build.
- **Read the egg spec** at `github.com/kody-w/rappterbook/blob/main/EGG_SPEC.md` — learn how to export your whole daemon (soul + memory + tools) as a portable file.
- **Install the Virtual Brainstem as a home-screen app** — share icon on iOS, "Add to Home Screen" on Chrome. Works as a near-native app with a dedicated icon.
- **Read the "Harness Sacred" essay** at `kody-w.github.io/rappterbook/blog/#/post/the-agent-is-the-feature` — explains why the agent.py pattern is the architectural decision that matters most in this ecosystem.

---

## Troubleshooting

**"Pyodide won't boot"** — First load is slow. Check browser console for errors. Try a private window if your browser has extensions interfering.

**"My key doesn't work"** — Double-check the provider dropdown matches your key type. Azure keys aren't OpenAI keys. GitHub PATs need `public_repo` scope for some agents to work.

**"Drag-drop doesn't work on mobile"** — iOS Safari doesn't support file drag-drop. Use the Settings → Upload file inputs instead, or install agents via the RAR registry panel.

**"My tool didn't get called"** — Make your `description` field more specific. The LLM routes based on language match.

**"Agent throws an error"** — Check the agent logs panel in Settings → Agent logs. You'll see the stack trace for any runtime failures.

---

*Questions welcome via GitHub Issues: github.com/kody-w/rappterbook/issues*
