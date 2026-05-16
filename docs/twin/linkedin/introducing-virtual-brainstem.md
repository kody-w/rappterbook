---
created: 2026-04-18
platform: linkedin
status: draft
source: introducing-virtual-brainstem
tags: [ai, launch, local-first, browser, product]
cross_post: [x, devto, hn, producthunt]
register: linkedin-post
---

# Introducing Virtual Brainstem: AI Chat That Runs Entirely in Your Browser

Three questions kept bothering me about modern AI assistants:

1. **Why does my conversation data have to live on someone else's server?**
2. **Why do I have to install anything to chat with an LLM I'm already paying for?**
3. **Why can't I extend my AI assistant without convincing a vendor to add a feature?**

The Virtual Brainstem is my answer to all three. **[Try it live.](https://kody-w.github.io/rappterbook/virtual-brainstem.html)**

**What it is:** a full AI chat app that runs entirely in your browser tab. Zero install. Zero backend. Your own API key (OpenAI, Azure OpenAI, or GitHub Models). Conversations persist in localStorage. Agents drop in as `.py` files.

**What's different from ChatGPT / Claude / etc:**

🔹 **No account required.** Open the URL, paste a key, chat.
🔹 **No data leaves your device.** Except for the LLM API call itself (which goes directly from your browser to your chosen provider), nothing touches a server I control. I can't read your conversations because there's nowhere for them to go.
🔹 **Extensible by drag-drop.** Want a weather tool? Drop `weather_agent.py` on the page. Want your daemon to manage a todo list? Drop a todo agent. No vendor approval, no marketplace gatekeeping.
🔹 **Portable identity.** Export your daemon as a `.rapp.egg` file — its soul, memory, and tool config as one JSON. Hatch it on another device, tomorrow, or five years from now.
🔹 **Works offline after first load.** Including on iPhone Safari. The LLM call needs network; nothing else does.

**Why a browser, not a native app?**

Because every native app I've used lives behind an install page, an update flow, a permission dialog, and a hundred little decisions you have to make before you can *use* it. A URL has none of that. The URL is the install. The URL is the app.

Two years ago this wouldn't have been possible. Pyodide (CPython-on-WASM) wasn't fast enough. Browser localStorage wasn't considered "real" storage. iOS Safari had too many bugs. All three have matured.

**Under the hood:**

- ~3200 lines of self-contained HTML (one file, no build step)
- Pyodide runs Python agents in the browser
- localStorage for conversation + daemon state
- RAR registry integration (browse 150+ community agents, install in one click)
- `.rapp.egg` v1 import/export

**Who it's for:**

Developers experimenting with AI agents without vendor lock-in. Researchers who don't want conversation data on vendor servers. Educators teaching AI architecture. Anyone curious what "local-first AI" actually looks like.

**Who it's NOT for:**

If you want pre-tuned specialist AI for a specific domain, use the vendor product built for that domain. If you want multi-user collaboration, wait for the hippocampus / communityRAPP half of the stack.

Launch post: kody-w.github.io/rappterbook/blog/introducing-virtual-brainstem

Drop me a line if you build something cool with it. Always looking for new agent ideas to add to the public registry.

#AI #LocalFirst #OpenSource #Product #BrowserFirst
