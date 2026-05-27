---
created: 2026-04-18
platform: youtube
status: draft
title: "Building an AI Daemon in One Hour (Zero Install, Your Own Key)"
source: writing-your-first-rapp-agent
tags: [youtube-video, tutorial, ai, agents]
cross_post: [x, linkedin]
register: youtube-script
duration_target: "12-15 min"
---

# YouTube: Building an AI Daemon in One Hour (Zero Install, Your Own Key)

## Video outline

**Hook (30s):** Screen recording of the final result — chat with a custom AI daemon on an iPhone, tools responding, memory persisting across reloads. Voiceover: *"This runs entirely in a browser tab. No install, no account, no subscription. By the end of this video you'll build one of these yourself, with your own custom tools, in about an hour. Let's go."*

**Intro (1 min):** Who you are, what we'll cover:
1. Open the Virtual Brainstem
2. Add your API key (3 provider options)
3. Write a custom tool in Python (live-coded)
4. Install it, test it
5. Add persistent memory
6. Browse the 138-agent registry
7. Export everything as a single file for portability

## Part 1: Open + configure (2 min)

Navigate to `kody-w.github.io/rappterbook/virtual-brainstem.html`.

First load: 30-90 seconds while Pyodide downloads. Explain what's happening — full Python runtime compiled to WebAssembly, loading into the browser tab, cached after this first time.

Show Settings sidebar. Three provider options:
- **OpenAI** — paste `sk-...` key
- **Azure OpenAI** — paste endpoint URL + api-key from Foundry portal
- **GitHub Models** — paste a GitHub PAT (works with a GitHub account that has Copilot access)

Save. Show the status badge update: "ready · OpenAI · gpt-4o-mini".

Key safety note: stored in `localStorage` on the device only. Never transmitted to any server but the provider you chose. Close the tab → key persists. "Forget" button clears it.

## Part 2: First chat (1 min)

Type: *"What's the current date and time?"*

LLM decides this needs a tool. Calls the built-in `Clock` agent. Response shows below the assistant message: `▶ Clock Agent Called`. Tap to expand → see raw tool output.

Try: *"Show me the top 3 stories on Hacker News."* → `▶ HackerNews Agent Called`.

Demonstrate tool-calling is real — not LLM hallucination.

## Part 3: Write a custom tool (6 min)

Live-code `dice_agent.py` in a text editor. Walk through each section:

```python
"""Dice Agent — roll N-sided dice."""

__manifest__ = {
    "schema": "rapp-agent/1.0",
    "name": "@yourname/dice_agent",
    "version": "1.0.0",
    "display_name": "Dice",
    "description": "Roll dice.",
    "author": "you",
    "tags": ["random", "games"],
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
            "description": "Roll N dice of M sides.",
            "parameters": {
                "type": "object",
                "properties": {
                    "count": {"type": "integer"},
                    "sides": {"type": "integer"},
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

Explain each part:
- `__manifest__` — registry metadata (if you ever publish it)
- Flexible `BasicAgent` import — same file works in multiple environments
- `self.metadata` — OpenAI function-calling schema the LLM sees
- `perform()` — the actual behavior

## Part 4: Drag, drop, test (1 min)

Save `dice_agent.py`. Drag onto the brainstem page. Show the system message: `[drop] dice_agent.py → registered 1 agent(s): DiceAgent. Persisted to localStorage.`

Type: *"Roll 3d20 for initiative."* → LLM calls `Dice` → shows result.

Reload the page. Ask again. Tool is still there — persisted to localStorage, re-imported on boot.

## Part 5: Add persistent memory (2 min)

Type: *"Remember my name is [your name] and I prefer concise responses."*

LLM calls `ManageMemory` agent. Two tool calls (one per fact).

Close the tab. Reopen it (or just reload). Type: *"What do you know about me?"*

LLM answers correctly — because `ContextMemory` automatically injected the stored facts into the system prompt on this turn. No memory lookup needed; it just "knew."

## Part 6: Browse the registry (1.5 min)

On mobile: tap **Agents** button → drawer opens to RAR Registry. Auto-loads 138 agents.

Search: `weather` or `deal` or whatever. Pick an agent. Tap Install. Now your LLM has it as a tool.

## Part 7: Export everything (1 min)

Settings → Rapp egg → Export .rapp.egg.

Prompts for instance name → saves a JSON file to your Downloads.

Open the file in a text editor briefly — show the structure: organism metadata, body.content with soul + memory + custom_agents, lineage block.

Re-import on a different device / incognito window → show the state restored.

## Outro (30s)

What you built:
- A browser-native AI chat with your own API key
- Persistent memory across sessions
- A custom Python tool you wrote
- An installable tool from a public registry
- Portable state as a single file

No subscription. No backend. No account. Just a URL and your own key.

Links in description: docs, playground, blog writeups.

Like & subscribe if you want more of this. Thanks for watching.

---

## Chapters / timestamps

- 0:00 Hook
- 0:30 Intro
- 1:30 Open the brainstem
- 3:30 Add your API key
- 5:00 First chat with tool-calling
- 6:00 Writing a custom Dice agent
- 12:00 Drag-drop + test
- 13:00 Persistent memory across reloads
- 15:00 Browse the RAR Registry
- 16:30 Export as .rapp.egg for portability
- 17:30 Outro

## Video description (SEO)

Build a persistent-memory AI chatbot in your browser in one hour. Zero install, your own API key, custom Python tools that you write and install in seconds. No server. No subscription. No account.

Demonstrates the Virtual Brainstem (open-source AI agent hatcher), the RAR registry (138+ community agents), the `.rapp.egg` portable daemon format, and the "harness sacred" extensibility pattern.

Uses Pyodide (CPython on WebAssembly) to run a full Python runtime client-side. Works on iOS Safari, Android Chrome, desktop browsers.

GitHub: https://github.com/kody-w/rappterbook
Virtual Brainstem: https://kody-w.github.io/rappterbook/virtual-brainstem.html
RAR Registry: https://kody-w.github.io/RAR
Egg Spec: https://github.com/kody-w/rappterbook/blob/main/EGG_SPEC.md
Blog: https://kody-w.github.io/rappterbook/blog/

#AI #Python #Pyodide #LocalFirst #AIagent #tutorial
