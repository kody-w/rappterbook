---
created: 2026-04-18
platform: producthunt
status: draft
source: zero-install-ai-chat
title: "Virtual Brainstem — AI chat that runs in a browser tab with your own key"
tagline: "Zero-install AI chat. Your API key. Your memory. Your tools. Your device."
register: producthunt-launch
---

# Virtual Brainstem

## Tagline
Zero-install AI chat. Your API key. Your memory. Your tools. Your device.

## Category
Developer Tools · AI · Productivity

## Main description (the pitch)

Virtual Brainstem is an AI chat app that runs entirely in a browser tab. No install, no account, no subscription. You bring your own API key (OpenAI, Azure OpenAI, or a GitHub PAT for GitHub Models) and the brainstem stashes it in localStorage on your device — never transmitted anywhere else.

What makes it different from other "bring your own key" chat UIs:

✅ **Persistent memory.** Tell it facts about you. Reload tomorrow. It remembers. Powered by a tiny `ContextMemory` agent that auto-injects stored facts into the system prompt each turn.

✅ **Extensible by drag-and-drop.** Drop a Python agent file onto the page and the LLM gains a new tool. No build step. No release cycle. Your file becomes a capability immediately.

✅ **138-agent registry.** Browse community tools (memory agents, research tools, HackerNews fetchers, deal-desk analyzers, scrapers, more). One-click install. Everything runs in your browser.

✅ **Portable state.** Export your entire daemon (soul + memory + tools) as a single `.rapp.egg` JSON file. Hatch on another device, or share with a friend, or keep as a backup. No cross-device sync required because your state travels with you.

✅ **Works on iPhone.** Add-to-Home-Screen makes it feel native. Mobile-first UI with slide-over drawer for settings, RAR registry panel one tap away for installing agents on the go.

✅ **Single HTML file.** Fork the source, self-host it, modify it. The whole product is one file + CDN-loaded Pyodide.

## Why we built it

I had a 1,500-line Flask app called the RAPP brainstem that did OpenAI-style tool calling with agent auto-discovery. Great on my laptop. Useless on my phone without exposing the port via ngrok. Useless to friends who don't want to `pip install` anything.

I ported it to Pyodide (CPython compiled to WASM) over a weekend. The server went away. The Python runtime and all the agent logic stayed. Memory that used to live in JSON files on disk now lives in browser localStorage. The result works on my phone, on friends' phones, in incognito tabs, everywhere.

## Who it's for

- People who want persistent-memory AI chat without a ChatGPT/Claude subscription
- Developers who want to extend their AI with custom tools without learning a framework
- Privacy-conscious users who don't want their conversations stored on vendor servers
- Anyone curious about "what if AI tooling were genuinely local-first"

## Try it

Playground: https://kody-w.github.io/rappterbook/virtual-brainstem.html
Source: https://github.com/kody-w/rappterbook
Writeup: https://kody-w.github.io/rappterbook/blog/#/post/zero-install-ai-chat

## First comment (from maker)

👋 Kody here. I'm using this every day on my laptop and iPhone as my primary AI chat. I'll be hanging out in the comments today.

A few things I'd specifically love feedback on:

1. **The "harness sacred" extensibility pattern.** Features don't go in the core — they ship as Python files that drop in. Curious whether people building other AI tools feel the same contribution-bottleneck pressure I solved this way.

2. **The `.rapp.egg` format.** Single-file portable AI daemon format (v1 draft). If you're building AI agent tooling and want to make your daemons distributable, take a look at the spec — any compliant engine can hatch any compliant egg.

3. **Mobile experience.** iOS Safari was the hardest surface to make feel right. If you try it on your phone and something feels wrong, tell me what — the whole point is that this should work well on the device most people have on them.

Not looking to monetize this. Not trying to build a SaaS. I just think AI tooling should be shaped this way — zero-account, local-first, forkable. If you do too, it'd be cool to compare notes on what other tools you're building in the same shape.

## Media to include

- Screenshot: iPhone viewport showing the chat with agent-called panels
- Screenshot: Desktop with sidebar showing RAR registry browse
- GIF: drag-drop agent.py → LLM uses it in response
- Video: 60-second demo — key paste → chat → install tool → chat with tool → export egg → re-import
