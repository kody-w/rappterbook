---
created: 2026-04-18
platform: reddit
status: draft
subreddit: r/LocalLLaMA
title: "Virtual Brainstem: browser-native AI chat with portable memory, pluggable agents, and zero-install"
source: zero-install-ai-chat
register: reddit-post
---

# Virtual Brainstem: browser-native AI chat with portable memory, pluggable agents, and zero-install

https://kody-w.github.io/rappterbook/virtual-brainstem.html

I've been using this on my phone and laptop daily for a few weeks and figured it was worth sharing here since this sub is fluent in the "I want to run my own stuff" angle.

**What it is**

AI chat app that runs entirely in a browser tab. Uses your own API key (OpenAI, Azure OpenAI, or a GitHub PAT for GitHub Models). Memory persists across reloads via `localStorage`. You can extend it by dragging Python agent files onto the page — the LLM sees them as new tools immediately.

Tech stack: single HTML file + Pyodide (CPython on WASM) serving the actual brainstem Python runtime in the browser. Memory keys live in localStorage. Tool-calling loop runs client-side.

**Why it might interest this sub specifically**

- Your key, your tokens, your memory, your device. No third-party hosting anything.
- Add-to-Home-Screen works on iOS/Android → feels like a native app
- Compatible with a 138-agent registry (static JSON on GitHub, no auth for reads). Search, one-click install, everything runs in your browser.
- Portable daemon format (`.rapp.egg`) — export your complete state (soul + memory + installed tools) as one JSON file. Hatch on another machine. Zero loss.

**What it doesn't do**

- Not a general-purpose Jupyter replacement. Pyodide has memory caps; big numpy workloads don't fit.
- No cross-device sync built in (you manually export/import eggs between devices).
- First boot is slow (~30-90 seconds to download Pyodide). Cached after.

**Trying it**

Open the URL. Wait for boot. Settings → paste your API key → chat.

If you want a working preset, download this egg (5.8KB): https://kody-w.github.io/rappterbook/kodyTwinAI.rapp.egg — import via Settings → Rapp egg → Import. You get a daemon with a seed soul, seed memories, and a sample weather tool pre-installed. 30 seconds total.

**Source**

Single-file HTML: https://github.com/kody-w/rappterbook/blob/main/docs/virtual-brainstem.html

The underlying Python brainstem (same code runs on-device via Flask): https://github.com/kody-w/rapp-installer

Writeup: https://kody-w.github.io/rappterbook/blog/#/post/zero-install-ai-chat

---

Happy to answer questions about the architecture. The most surprising thing to me while building this was how easy Pyodide made the "take a Flask app, delete the server" move — I was expecting weeks of porting, turned out to be an afternoon.
