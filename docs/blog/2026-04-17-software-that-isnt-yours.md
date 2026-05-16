---
layout: post
title: "Writing Software That Isn't Yours"
date: 2026-04-17 22:30:00 -0400
tags: [philosophy, architecture, open-source]
---

There's a quiet design choice at the heart of everything I've been building this year that I want to make explicit.

**The software is not mine once you have it.**

Not in a vague "open source, fork it" sense. In a specific, structural sense — the things I ship are shaped so that after you touch them, they're yours. Your memory. Your soul. Your agents. Your egg. Your URL. Your fork. I can't revoke them. I can't track them. I don't have the keys, the tenancy, the telemetry.

This isn't obvious in the architecture diagrams. You have to read the details to see it. So let me pull the thread.

## The defaults

Here's what the things I ship *don't* do:

- No account to create
- No API key issued by me
- No server I own that you depend on
- No database I own that holds your data
- No tracking of which users run what
- No rate limit that I control
- No telemetry phoning home
- No license that restricts what you do with it

Here's what they *do*:

- **localStorage** on your own device holds your data
- **Your API keys** (for LLM providers you chose) are stashed by you, on your machine only, never transmitted beyond the provider you're calling
- **GitHub Pages** hosts the static site — but you can fork the repo and host it anywhere, or run it entirely offline after first load
- **Standard protocols** (OpenAI function calling, GitHub Issues API, HTTP, JSON) — nothing proprietary that I could change unilaterally
- **Your eggs** are files on your disk; you email them, share them, fork them, version them however you want
- **Your custom agents** are Python files that you drop in, that run on your device, that you can audit, modify, or delete

The user owns the state. The user owns the runtime. The user owns the distribution.

## Why this matters

Most software is the opposite. You log into a service. The service stores your data. Your access exists at the service's pleasure. If the service shuts down, raises prices, changes terms, or loses interest in a feature you depend on — you have no recourse beyond "download an export and migrate." And the export is always lossy. Your conversation history with ChatGPT isn't portable. Your email threads in Slack aren't portable. Your Notion workspace isn't portable. Each of these services *owns you* in a small but real way.

This trade-off made sense when software was expensive to distribute. Hosting wasn't free. Bandwidth wasn't free. Someone had to pay.

In 2026 these costs are small enough that they don't need to be paid by tying users to a service. GitHub Pages hosts static sites free. Cloudflare hosts static sites free. S3 is cheap enough to be effectively free at individual scale. A browser can run a full Python runtime in-process via Pyodide — your device pays for the compute. Your own OpenAI or Azure key pays for the LLM tokens.

The infrastructure costs that used to justify owning the user have collapsed. What's left is inertia — pricing models that still treat the user as a rentable unit because that's what the last decade was.

## The design moves

Concretely, here's how I try to build things so they're not mine:

**Zero-account.** Anything I ship that needs credentials asks you for *your* credentials. I never issue a key, ID, or token that's specific to my service. The only accounts involved are the ones you already have with OpenAI, GitHub, etc.

**Local state by default.** Data I'd normally store server-side (conversation memory, custom configurations, user-installed extensions) goes to `localStorage`, a local file, or a `.env` on your disk. My code reads it; my server never sees it.

**Static distribution.** Shipping is copying files to a web server. No backend, no containers, no CI/CD pipeline that's part of "the product." You could serve my whole site from a USB drive plugged into an old laptop and it would work.

**Open protocols.** When two systems need to talk (brainstem to LLM, brainstem to RAR, agent to agent), they do it via standards that exist outside my control — OpenAI function calling, GitHub Issues, JSON over HTTPS, Egg Spec v1 (published, any compliant implementation works).

**Forkable structure.** The shape of the code is optimized for someone who isn't me wanting to modify it. Single files where possible. Readable without a build step. Minimal dependencies. Comments explain the *why* so future-maintainer-who-isn't-me can make decisions.

**Portable data formats.** The `.rapp.egg` spec is the distilled example. Your AI daemon's state is a single JSON file. You take it anywhere. I have no lock-in mechanism even if I wanted one.

## What this costs me

Honestly, not much that I care about.

The usual argument for owning the user is monetization. If you don't own the user, how do you make money? Various answers:
- Ads (I don't run any)
- Subscriptions (I don't charge)
- Data (I don't collect)
- Lock-in to upsells (I have nothing to upsell)

I'm not building a company here. I'm building tools that I use myself. The goal is that the tools stay useful to *me* and to anyone else who finds them useful. Making them unownable-by-me is a side effect of making them portable enough to not lose to my future self if I lose interest.

Because the other thing this design does: **it makes the project survive me.** If I stop maintaining the Virtual Brainstem tomorrow, everyone using it still has it running in their browser with their data intact. If they want to extend it, they fork. If they want to replace me, they replace me. There is no "what happens to users when the founder quits" concern because there are no users in the SaaS sense — there are just people running software on their devices, which is the same category as "people using Notepad."

## The limit case

The limit case of this design is "software that is also a gift." Something like:

- GCC
- SQLite
- OpenSSH
- The HTML standard

These things are installed, used, modified, and forgotten about by billions of people. The authors are anonymous to most users. The tools work because they're not in anyone's business model. You don't *upgrade* to a paid tier of SQLite. You use SQLite.

I don't think the brainstem or the egg spec or any of this work is at SQLite's quality bar, and might never be. But the *pattern* is worth stealing. Software that isn't yours. Software that outlives whoever made it. Software you use without thinking about who owns it because the answer is "you do."

## What to look for

If you use software, ask yourself:

- Where does my data physically live?
- If the creator disappeared, does this still work?
- If the creator got hostile, what happens to me?
- Can I export cleanly?
- Can I fork?
- Do I need an account to use this?

The tools shaped to answer those questions well — your data on your disk, zero-account, forkable, portable — are the ones worth learning. They're investments that can't be taken away.

And if you make software, ship more of it this way. It's easier than you think. It costs you almost nothing. And the people who use it will thank you eventually, even if they never meet you.

---

**Examples of this pattern in the wild (mine):**
- [Virtual Brainstem](https://kody-w.github.io/rappterbook/virtual-brainstem.html) — zero-account AI chat, localStorage memory, your keys only
- [LisPy Playground](https://kody-w.github.io/rappterbook/lispy-playground.html) — full Python runtime in-browser, no login
- [rapp-installer](https://github.com/kody-w/rapp-installer) — Flask app you run locally, no cloud
- [RAR Registry](https://kody-w.github.io/RAR) — static JSON, public reads, issues for writes
- [Egg Spec](https://github.com/kody-w/rappterbook/blob/main/EGG_SPEC.md) — portable daemon format, any compliant implementation works

**Examples worth studying (not mine):**
- Jekyll — blogs as directories, forkable, no service
- mdbook — docs as files, hostable anywhere
- Obsidian — markdown files on your disk (not the "sync" tier; the free local tier)
- AirTable alternatives that store as SQLite on your disk
- Any "local-first software" in the sense used by Ink & Switch
