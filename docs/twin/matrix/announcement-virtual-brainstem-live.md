---
created: 2026-04-18
platform: matrix
status: draft
title: "Virtual Brainstem live — browser-native AI chat, local-first, yours"
source: zero-install-ai-chat
register: matrix-announcement
room: "#rappter-announce:matrix.org"
---

# Matrix announcement

**[Rappter] Virtual Brainstem is live — browser-native AI chat, local-first**

Shipped this week: a full AI chat app that runs entirely in your browser tab. Zero install. Your own API key. Persistent memory via `localStorage`. Drop-in agent extensibility. Works on iPhone.

- **Try it:** https://kody-w.github.io/rappterbook/virtual-brainstem.html
- **Source:** https://github.com/kody-w/rappterbook (single HTML file — you can fork it)
- **Companion specs:** `.rapp.egg` portable daemon format (v1 draft-adopted)
- **Registry:** `kody-w.github.io/RAR` — 138+ community agents, one-click install

Aligns with the local-first software ethos. No account required. No data on my servers (because I don't have servers). Compatible with OpenAI, Azure OpenAI, and GitHub Models (bring-your-own-key for all).

Twelve blog posts this week cover the architecture end-to-end: `kody-w.github.io/rappterbook/blog/`

Matrix-appropriate use cases that jumped out at me during build:
- Running a persona-tuned AI privately without the conversation history hitting any vendor
- Shipping agent tools between rooms as drag-drop `.py` files
- Exporting a daemon's complete state as a `.rapp.egg` to hand off between devices/users

Feedback welcome in this room or via GitHub Issues.

— Kody
