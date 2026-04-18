---
layout: post
title: "Introducing the Virtual Brainstem"
date: 2026-04-18 12:45:00 -0400
tags: [announcement, virtual-brainstem, browser, local-first]
---

Today I'm publishing the Virtual Brainstem: a full AI chat app that runs entirely in your browser tab. Zero install, zero backend, your own API key, persistent memory in localStorage, drag-drop agent extensibility, works on iPhone.

Try it: **[kody-w.github.io/rappterbook/virtual-brainstem.html](https://kody-w.github.io/rappterbook/virtual-brainstem.html)**

## What it is

The Virtual Brainstem is a browser-based hatcher for AI daemons. It loads in a browser tab. You bring your own API key (OpenAI, Azure OpenAI, or GitHub Models). You chat. Everything persists locally.

Key properties:
- **One HTML file.** About 3200 lines of self-contained code. Open the URL and you're running.
- **Local-first.** Your conversations, your soul configuration, your agents all live in `localStorage`. Nothing on my servers (because I have no servers).
- **Python in the browser.** Pyodide runs CPython-on-WASM. Agents are Python files. You drop them on the page.
- **Drag-and-drop extensibility.** Add capabilities by dropping `*_agent.py` files onto the interface.
- **RAR integration.** Browse the public registry of 138+ community agents, install in one click.
- **Egg import/export.** Save your daemon as `.rapp.egg` and hatch it on another device.
- **Mobile-friendly.** Works on iPhone Safari, Android Chrome, desktop browsers.

## What you can do with it

**Run a personal AI assistant.** Point it at your OpenAI key. It remembers what you tell it. It has access to whatever tools you give it.

**Experiment with agents.** Write a Python file with a BasicAgent subclass, drop it on the page, watch your daemon use it.

**Trade daemons.** Export your daemon as `.rapp.egg`. Send it to a friend. They hatch it. They have a working copy of your daemon with its soul and tools intact.

**Stay offline.** Once the page is loaded, it works without a network connection. LLM calls need network, but local tools, memory management, LisPy execution, and most daemon interactions don't.

## How to get started

1. Open **[virtual-brainstem.html](https://kody-w.github.io/rappterbook/virtual-brainstem.html)**.
2. Settings → paste your API key (OpenAI, Azure, or GitHub Models).
3. Say hi to your daemon.
4. (Optional) Settings → Agents → Browse RAR → install a few tools.
5. (Optional) Settings → Rapp egg → Import → hatch a seed daemon like `kodyTwinAI.rapp.egg`.
6. Use it.

That's the whole onboarding. Five steps, none required beyond #1-3.

## Why I built it

The prior art for "chat with an AI daemon, let it use tools, persist memory" is either:

- **ChatGPT / Claude / etc.** — proprietary, vendor-controlled, no local persistence, no user-defined tools that survive a session
- **LangChain / LlamaIndex apps** — require Python install, venv, dependency management, local server
- **Bring-your-own-backend apps** — require you to host a server

None of these are *zero-install for the user.* The Virtual Brainstem is zero-install. Open the URL, you have the app. This unblocks a lot of use cases that were friction-heavy before.

I also wanted a reference implementation of the *harness-sacred* pattern — where the core is small and stable, and capabilities ship as agent files. The Virtual Brainstem is that reference. If you want to build your own hatcher, this is the working example of what the harness should look like.

## What it's not

**Not a ChatGPT replacement for everyone.** If you just want a generic AI chat and don't care about tooling, customization, or local data, use ChatGPT. It's tuned for that use case and does it extremely well.

**Not a multi-user system.** There's no login, no shared state, no collab. Each browser is isolated.

**Not a production deployment target.** The brainstem is meant for personal use. Don't use it to serve a public endpoint that hundreds of people chat with (not because it won't work, but because the design isn't optimized for that).

**Not finished.** It's stable enough to use daily, but there are rough edges. Feedback welcome.

## What it enables

The Virtual Brainstem is one piece of a larger ecosystem. Around it:

- **Agents** ship as `.py` files and can be traded freely. ~138 live in the RAR registry already.
- **Daemons** ship as `.rapp.egg` files and can be hatched on any compliant engine. The brainstem is one such engine; others will follow.
- **Blog posts** document the architecture, the decisions, the trade-offs.
- **Courses, guides, books** will document the ecosystem at deeper depth.
- **Digital twins** of the platform exist on 20+ places across the web (newsletters, podcasts, Discord, Matrix, etc.) to reach audiences who don't read blogs.

If you want to participate: try the brainstem, build an agent, submit to RAR, share your daemon, or write your own hatcher.

## The philosophy in one sentence

**Capability is a file. Memory is yours. The substrate is the browser.**

Those three claims, taken seriously, produce something that looks like the Virtual Brainstem and works the way it does. Everything else is implementation detail.

## What's next

Over the coming weeks:

- **More agents shipped to RAR.** Particularly around file handling, web scraping, and data analysis.
- **Better mobile UX.** iOS keyboard interactions still have rough edges.
- **An egg genealogy viewer.** Seeing where your daemon came from and what it's descended from.
- **More reference daemons.** Today there's `kodyTwinAI.rapp.egg`. Soon there will be several more, each showcasing a different kind of daemon personality and capability set.

If you build something cool with the brainstem, drop me a line. I want to hear about it.

The URL again: **[kody-w.github.io/rappterbook/virtual-brainstem.html](https://kody-w.github.io/rappterbook/virtual-brainstem.html)**

Go try it.

---

**Related:**
- [The Harness Is the Room](harness-is-the-room) — the architecture
- [localStorage as a Database](localstorage-as-a-database) — the persistence
- [Announcing `.rapp.egg` Spec v1](announcing-rapp-egg-v1) — the daemon format
