---
layout: post
title: "Zero-Install AI Chat in Your Browser (With Your Own Key)"
date: 2026-04-17 21:45:00 -0400
tags: [consumer, ai-agents, browser, practical]
---

I made a thing over the weekend that I now use on my phone every day. It's an AI chat — same experience as ChatGPT or Claude — except:

- It runs entirely in a browser tab. Nothing to install.
- It uses **your** API key (OpenAI, Azure OpenAI, or a GitHub PAT). No subscription fees.
- It remembers facts about you across sessions, persisted in your browser.
- You can extend it by dropping in Python agent files that become tools the LLM can call.

It's called the **Virtual Brainstem**, live at: [kody-w.github.io/rappterbook/virtual-brainstem.html](https://kody-w.github.io/rappterbook/virtual-brainstem.html)

Here's how to make it yours in 90 seconds.

## Step 1: Open it

On your phone or laptop, open the URL. First visit takes 30-90 seconds — it's downloading a Python runtime into your browser (Pyodide, about 10MB). Subsequent visits boot in seconds because the browser caches everything.

You'll see a chat pane and, on desktop, a settings sidebar on the right. On mobile, tap **Settings** in the header.

## Step 2: Add a key

You need an API key. Three options:

**OpenAI.** A paid key from platform.openai.com. Models like `gpt-4o-mini` (cheap, fast) or `gpt-4o` (smarter, more expensive). Tens of cents per day of casual chat.

**Azure OpenAI.** If you have an Azure subscription with OpenAI deployed, grab the endpoint URL + api-key from the Microsoft Foundry portal. Works the same way — same model quality, often cheaper for heavy use.

**GitHub Models.** If you have a GitHub account with Copilot access, run `gh auth token` to grab a Personal Access Token. The brainstem uses it to hit `models.github.ai` — you get access to OpenAI models (gpt-4o), Claude, Llama, and others through GitHub Models.

In the Settings sidebar, pick your provider, paste the key, click **Save**. Or — if you have a local `.env` file with these already set — upload it via the **Upload .env file** button. Both paths stash the key in `localStorage` on your device only. Nothing transmitted. No account to create.

## Step 3: Chat

Type a message. Hit Enter. The brainstem shows `▶ thinking…` while it talks to the LLM.

If the LLM decides to call a tool (for example: "what time is it?" triggers the Clock tool; "what's on Hacker News?" triggers the HackerNews tool), you'll see the call name appear under the response as `▶ Clock Agent Called` — tap it to see the raw tool output.

## Step 4: Build memory

Try: *"Remember that my name is [yours] and I'm learning Rust."*

The LLM will call the `ManageMemory` agent, which writes the fact to `localStorage`. You'll see it happen: `▶ ManageMemory Agent Called`.

Now **close the tab**. Come back tomorrow. Type: *"What do you remember about me?"*

The `ContextMemory` agent auto-injects everything you've told it into the system prompt, so the LLM answers with your name and your learning goal. No database. No backend. Just your browser's localStorage.

Ask it to remember preferences, recurring tasks, names of people in your life, project contexts. It persists. Forever, until you clear browser data.

## Step 5: Install tools

The brainstem ships with 4 built-in agents (memory, HackerNews, clock, echo). For more, tap **Agents** in the header (mobile) or scroll to the RAR Registry section (desktop).

138 community agents are available via the RAR registry — search, one-click install. Examples:

- **deal_desk** — sales scenario analysis
- **rappter_engine** — monitor fleet state
- **agent_workbench** — test harness for agents
- **learn_new_agent** — an agent that *creates new agents* when you describe what you want

Tap Install. The agent's Python source is fetched, loaded, persisted. The LLM sees the new tool immediately.

## Step 6: Add to Home Screen (iOS)

On iPhone: share icon → **Add to Home Screen**. You now have a tappable icon that opens the brainstem as a near-native app with no browser chrome. Dark status bar. "Brainstem" as the app name.

On Android: Chrome's menu → Install app. Same deal.

## What this replaces

For the casual-chat use case — the thing most people use ChatGPT for — this replaces the subscription. You pay only for the tokens you actually use, direct to OpenAI or Azure. At typical usage (a couple dozen messages per day), that's cents per week.

For the "I want my AI to remember me" use case, this replaces *nothing else that exists* in a free tier. Claude and ChatGPT paid tiers have memory features. No free tier gives you durable, portable, across-device memory without a subscription. Your brainstem's localStorage is yours. You can export it. You can migrate it. You can wipe it.

For the "I want to extend my AI with custom tools" use case, this is way simpler than the current landscape. Writing a tool for ChatGPT requires uploading to their custom GPT system. Writing a tool for Claude requires working with MCP. Writing a tool for the brainstem means dragging a `.py` file onto the page.

## Where the browser breaks down

Be honest about limits:

- **First boot is slow.** 30-90 seconds on first visit. Acceptable as a one-time cost.
- **Big workloads don't fit.** iOS Safari caps the WebAssembly heap. Don't try to train an ML model in here. Do try to chat, manage tasks, research topics, summarize text.
- **Cross-device sync isn't built in.** Each device has its own localStorage. You can export your state via the egg format and re-hatch on another device — but it's manual, not seamless.

For a chat tool that lives in a URL, these trade-offs are fine.

## What to try first

If you install one thing, install the Weather agent or the HackerNews agent. The pattern becomes clear: you ask, the LLM calls the tool, the tool returns live data, the response is grounded in reality instead of training data.

Then try telling it personal facts. Close the tab. Come back. Ask what it remembers.

Then, if you're still here, write your own agent. `basic_agent.py` has a 20-line interface. Your first tool can be whatever you want. Drop the file. It's yours.

---

**Quick links:**
- [Virtual Brainstem](https://kody-w.github.io/rappterbook/virtual-brainstem.html)
- [RAR Agent Registry](https://kody-w.github.io/RAR) — 138+ community tools
- [Source code](https://github.com/kody-w/rappterbook/blob/main/docs/virtual-brainstem.html) — one HTML file, you can fork it
- [rapp-installer](https://github.com/kody-w/rapp-installer) — if you prefer an on-device Python version
