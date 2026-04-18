---
created: 2026-04-18
platform: x
status: draft
title: ".rapp.egg v1 — portable AI daemons as 5KB JSON"
source: announcing-egg-spec-v1
cross_post: [linkedin, devto, hn]
register: x-thread
---

# Thread: .rapp.egg v1 ships

**1/**
Your AI assistant is trapped wherever you made it.

Your personalized ChatGPT lives on ChatGPT's servers. Your custom Claude project lives in Anthropic's account. Your bespoke LangChain agent lives on the one laptop where you set up the venv.

None of it is portable. That's the bug. 🧵

**2/**
This week I shipped `.rapp.egg` Spec v1 — a 5KB JSON file format that captures an entire AI daemon and lets it hatch on any compliant engine.

Soul + memory + tools + metadata, all in one file. Email it. USB stick it. Paste it into a chat. Archive it for five years.

**3/**
What's IN the egg:
• soul (the system prompt — personality, priorities, behavior)
• memory (seed facts, preferences, context)
• tools (by reference — resolved at hatch time)
• metadata (name, author, date, optional parent pointer)

Total weight: typically 5-50KB.

**4/**
What's deliberately NOT in the egg:
• API keys (eggs are shareable; keys stay on your device)
• The LLM model itself (hatcher picks; eggs work with whatever's available)
• Session chat history (per-instance, not per-daemon)
• A filesystem image (this is NOT Docker)

**5/**
Why not Docker?

Docker freezes the *substrate* below your code. That's the right move when you need reproducibility (databases, crypto pipelines).

It's wrong for AI daemons. Daemons need *substrate mobility* — to ride on top of whatever infra gets better. An egg that locked to GPT-5.4 couldn't use GPT-5.5 tomorrow.

**6/**
The egg is a declaration of intent. "I want the dice roller tool." Not "here are the exact bytes of dice_roller.py compiled against this libc."

The hatcher resolves tool references at hatch time. Tools can be upgraded independently of eggs. Tools can even be *substituted* — Python version swapped for LisPy version, same interface.

**7/**
Two hatchers exist today:

• Virtual Brainstem — browser-based, one HTML file, uses Pyodide: kody-w.github.io/rappterbook/virtual-brainstem.html

• rapp-installer — native Python/Flask, got egg-compliance this week

The second hatcher surfaced interop bugs that tightened the spec. This is why a format needs at least 2 implementations before it's real.

**8/**
Since launch ~2 weeks ago:
• ~100 hatches of the reference seed (kodyTwinAI.rapp.egg)
• First lineage forks with proper parent pointers
• RAR agent registry crossed 150 agents

A small ecosystem is forming. Eggs are becoming the unit of trade.

**9/**
If you want to build a third hatcher — CLI, Slack bot, mobile app, Elixir, Rust, whatever — the spec is implementation-weekend-sized. Read it, implement reader-compliance, test interop with the Virtual Brainstem, ship.

I'll link compatible hatchers in the spec doc as they appear.

**10/**
Spec: github.com/kody-w/rappterbook/blob/main/EGG_SPEC.md
Hatcher: kody-w.github.io/rappterbook/virtual-brainstem.html
Seed: kody-w.github.io/rappterbook/kodyTwinAI.rapp.egg
Why-not-Docker writeup: kody-w.github.io/rappterbook/blog/egg-vs-docker

AI daemons should be as portable as documents. That's the goal.

/end
