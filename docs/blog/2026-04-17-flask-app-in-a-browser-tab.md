---
layout: post
title: "A Flask App That Lives in a Browser Tab"
date: 2026-04-17 21:30:00 -0400
tags: [pyodide, brainstem, browser, wasm, architecture]
---

For a few months now I've had a Flask app called the RAPP brainstem. It's about 1,500 lines of Python. It runs on `localhost:7071`. It loads a `soul.md` file as a system prompt, auto-discovers Python agent files from an `agents/` directory, and uses GitHub Copilot as the LLM to do tool-calling over an OpenAI-style function-calling API.

This week I deleted the server part. The app still works.

## The exercise

The brainstem's architecture is fundamentally:

1. Load soul.md
2. Load agents from `agents/`
3. Accept a user message
4. Build OpenAI chat-completion request with agents as tool defs
5. If the LLM asks for tool calls, dispatch, feed results back
6. Return the final response

None of those steps *require* a server. The Flask layer is incidental — it exists because Python doesn't have a UI runtime of its own, so you slap Flask on top to get a web UI.

But if Python could run *in the browser*, Flask goes away. The UI is the DOM directly. The Python logic runs client-side. The "server" is a myth.

Python runs in the browser now. It's called **Pyodide** — CPython compiled to WebAssembly, loadable from a CDN with one script tag, ~10MB first-load, cached thereafter. It exposes the full standard library plus some native packages (numpy, pandas, scipy) as pre-built wheels.

So I ported the brainstem to a single HTML file.

## What the port actually looked like

`virtual-brainstem.html` — one file, ships at [kody-w.github.io/rappterbook/virtual-brainstem.html](https://kody-w.github.io/rappterbook/virtual-brainstem.html).

The structure:

- **HTML**: chat pane + sidebar drawer. Plain semantic elements.
- **CSS**: dark theme, mobile-responsive, iOS safe-area-inset aware.
- **JS**: loads Pyodide from jsdelivr. Writes the brainstem's Python modules into Pyodide's in-memory filesystem. Imports them. Pokes/pulls state.
- **Python**: the brainstem logic. Same `BasicAgent` base class. Same chat loop (up to 3 rounds of tool calls). Same agent auto-discovery.

The tricky parts:

### Substrate swap: disk → localStorage

On-device, the brainstem persists soul to `soul.md`, memory to JSON files, agent source to `agents/*.py`. In the browser, all of that becomes `localStorage` with keys like `brainstem_soul`, `brainstem_memory_shared`, `brainstem_custom_agents`.

A thin shim module — `AzureFileStorageManager` — presents the rapp-installer's storage interface (`set_memory_context`, `read_json`, `write_json`) backed by localStorage instead of Azure Blob. Same shape; different bytes underneath. The existing memory agents (ManageMemory, ContextMemory) run unmodified against the shim.

### Module system: `/brainstem/agents/`

Agent files from `rapp-installer` expect to `from agents.basic_agent import BasicAgent`. In a browser, there's no `agents/` directory — there's no *disk*. But Pyodide gives you a virtual filesystem.

On boot, the HTML writes `basic_agent.py`, `manage_memory_agent.py`, etc. into `/brainstem/agents/`, adds `/brainstem` to `sys.path`, and now `from agents.basic_agent import BasicAgent` resolves. The agent files run verbatim. Every import the on-device version does, the browser version does too.

When the user drag-drops a new `.py` file, the handler writes it to `/brainstem/agents/` and calls `importlib.import_module`. Same pipeline. Hot-loading works because it's just filesystem writes + imports, and both exist in Pyodide.

### LLM calls: fetch instead of requests

The on-device brainstem uses `requests.post(...)` to hit the LLM API. In Pyodide, `requests` doesn't natively work against arbitrary origins because it uses sync sockets and the browser blocks those.

Swap to `js.fetch` via Pyodide's JS interop. The Python code goes:

```python
from js import fetch
from pyodide.ffi import to_js
from js import Object

opts = to_js({
    "method": "POST",
    "headers": {"content-type": "application/json", "authorization": f"Bearer {key}"},
    "body": json.dumps(body),
}, dict_converter=Object.fromEntries)
resp = await fetch(url, opts)
```

`dict_converter=Object.fromEntries` is the gotcha — Pyodide's default converts Python dicts to JS `Map`, and `fetch()` silently ignores Map-valued headers. Swap to `Object.fromEntries` and headers actually ship. (Found this the hard way. Spent an embarrassing amount of time staring at a 401 that didn't say anything about auth headers.)

## What gets better in the browser

**Zero install.** Open a URL. You have a full brainstem. No `pip install`, no `gh auth login`, no port conflict with the 5 other services you have on localhost. Open URL. Chat.

**Mobile support by accident.** I didn't set out to make the brainstem work on an iPhone. It just did, once I fixed the viewport meta and bumped input fonts to 16px. Now the same tool I was using on a laptop runs in my pocket. Walk around. Chat with my AI. Install agents from the RAR registry via the Agents button. Memory persists across visits.

**Distribution becomes a link.** I showed a friend what I was working on by sending them a URL. They clicked. It worked. There was no install step. They said "huh" and started using it.

## What gets worse

**Cold start is slow.** 30-90 seconds for Pyodide to download and boot on first visit. After that, cached. But first visit is brutal.

**No real filesystem.** Agents that want to read/write host files can't. `virtual_os` plus localStorage cover most cases, but if you really need `os.path.exists` against a user's actual `/Users/kody/Projects/`, the browser can't help you.

**Memory limits.** iOS Safari caps Pyodide's heap aggressively. Big numpy arrays might not fit. Most agent workloads aren't big numpy arrays, so this matters rarely — but it does matter.

**One tab = one session.** Two tabs = two separate brainstems. Coordinating between them is harder than between two Flask instances on different ports.

## The bet

The bet I'm making is that for an agent-facing dev tool — a forge, in the language of the [Forge and Theatre post](forge-and-theatre) — the browser's limitations don't matter. You're tuning prompts, dropping in agents, testing memory. None of that requires a real OS.

And the upsides — zero-install, mobile-by-accident, distribution-via-URL — are transformative. The on-device brainstem at `localhost:7071` was a developer tool. The browser brainstem is a consumer product.

Same code. Same contract. Different blast radius.

Python in the browser stopped being a demo a while ago. If you've got a Flask app that's fundamentally just "take input, run Python, show output," and you haven't tried porting it — it's worth an afternoon. Half your users don't want to `pip install` your thing. Some of them are using a phone.

---

**Try it:**
- [virtual-brainstem.html](https://kody-w.github.io/rappterbook/virtual-brainstem.html) — the browser brainstem
- [rapp-installer](https://github.com/kody-w/rapp-installer) — the original Flask version
- [Pyodide docs](https://pyodide.org) — the runtime that made this possible
