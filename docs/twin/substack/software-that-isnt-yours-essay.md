---
created: 2026-04-18
platform: substack
status: draft
title: "Writing Software That Isn't Yours"
source: software-that-isnt-yours
tags: [local-first, architecture, philosophy, open-source]
cross_post: [linkedin]
register: substack-essay
---

# Writing Software That Isn't Yours

*On the design choice that sits quietly behind everything I've been building this year.*

---

There's a quiet design decision at the heart of everything I've been shipping lately that I want to make explicit. Not because it's clever. Because it's structural, and I think more software should be shaped this way, and I'm not sure the pattern has a good name yet.

**The software is not mine once you have it.**

Not in the vague "it's open source, fork it if you want" sense. In a specific, structural sense — the things I ship are shaped so that after you touch them, they're yours. Your memory. Your configuration. Your data. Your API keys. Your agents. Your fork. I can't revoke them. I can't track them. I don't have the keys, the tenancy, the telemetry. There's no dashboard I log into that shows me who's using what.

This isn't how most software works, and the gap is worth dwelling on.

## The shape of ownership in most software

When you use ChatGPT, your conversation history lives on OpenAI's servers. Your access to those conversations exists at OpenAI's continued pleasure. If OpenAI raises prices, changes terms, shuts down the product, or decides you violated a policy — those conversations go away, or become expensive to retrieve, or become impossible to search.

Same with Notion. Same with Slack. Same with Airtable. Same with every SaaS tool whose "export" function produces a sad JSON file with half the semantic richness of the original — no threading, no comments, no references, no search index. The export is technically compliant with the spirit of data portability and practically useless for continuing to work with what you exported.

This trade-off — you get nice software, they own your data — made sense when software distribution was expensive. Hosting wasn't free. Bandwidth wasn't free. CPU cycles at scale weren't free. Someone had to pay, and the business model that emerged was: users pay (via money or attention or data), vendors host, vendors own.

**That trade-off is largely obsolete in 2026.**

## What changed

GitHub Pages hosts static sites for free. Cloudflare Pages hosts static sites for free. S3 and R2 host static objects for cents per month at individual scale. Your browser can run a full Python interpreter in-process via Pyodide — your own device pays for the compute, no server-side runtime required. Your own OpenAI or Azure or Anthropic API key pays for the LLM tokens, giving you per-usage pricing instead of subscription markup.

The infrastructure cost justifications for owning users have mostly collapsed. What's left propping up the old model is inertia and business-model momentum — pricing strategies designed for 2012 still running in 2026 because nobody's gotten around to updating them.

So I've been trying to ship things under the *new* constraints. What does software look like when you ignore the legacy business logic and build for what the infrastructure actually costs today? The answer, for me, has turned out to be: zero-account, local-state-by-default, static-distribution, open-protocol, forkable-structure, portable-formats software.

## What that looks like in practice

Concretely, here's how this plays out across the things I've shipped:

**Zero-account.** Nothing requires users to create a login with me. Credentials they use are credentials they already have — OpenAI API key, Azure subscription, GitHub Personal Access Token. I never issue a service-specific ID, token, or session. If you stopped using my stuff tomorrow, there would be nothing to deactivate because there was never anything active on my side.

**Local state by default.** Anything I'd normally store server-side — conversation memory, configurations, installed extensions, user preferences — goes to browser `localStorage`, a local `.env` file, or explicit user files on disk. My code reads it; my server never sees it (because there is no server).

**Static distribution.** Deploying is copying HTML/CSS/JS to a static host. GitHub Pages, your own S3 bucket, a USB stick plugged into an old laptop — all of these work. There is no backend. No container orchestration. No CI/CD pipeline that's part of "the product." No API I could rate-limit someday if I became mean.

**Open protocols.** Where two systems need to talk — AI chat app to LLM provider, agent registry to GitHub, daemon serialization to any compliant hatcher — they use standards that exist outside my control. OpenAI function calling. GitHub Issues API. JSON over HTTPS. The Egg Spec (published; any compliant implementation works). I'm not a gatekeeper; I'm a contributor to standards that would survive me.

**Forkable structure.** Single-file HTML pages where possible. Readable without a build step. Minimal dependencies. Comments explain the *why*, not just the *what*. The code's implicit audience is "a future maintainer who isn't me and whose first contact with this is clicking 'view source.'"

**Portable formats.** A complete AI daemon's state — system prompt, persistent memory, installed tools — fits in one JSON file under the `.rapp.egg` spec. Users can email eggs, fork eggs, version eggs, migrate them to new hatchers. I have no lock-in mechanism even if I wanted one.

## What this costs me

Monetization, roughly. I can't charge subscriptions to people who don't have accounts with me. I can't sell data I don't collect. I can't upsell premium features inside a product I'm not renting out. Standard SaaS revenue models require the pieces I'm deliberately not building — session management, user databases, usage tracking, feature flags — so those models are off the table.

I'm okay with that. I build tools I use myself. The goal is that they stay useful to me and to whoever else finds them useful. Designing them to be unownable-by-me is a side effect of making them portable enough to outlive my future self's occasional loss of interest in them.

The other thing this design does is subtle but, I think, important: **it makes projects survive the maintainer.**

If I stop maintaining the Virtual Brainstem tomorrow — get hit by a bus, or just get bored, or take a full-time job at Google that eats all my evenings — everyone currently using it still has it. Their data is in their browser. Their API keys are on their devices. The static files are mirrored in any number of places (GitHub Pages, anyone's fork, anyone's local clone). They can keep using it. They can extend it. They can replace me with someone else, or with themselves.

There is no "what happens to users when the founder quits" concern, because there are no users in the SaaS sense. There are just people running software on their devices, which is the same category as "people using Notepad."

This is profoundly different from the exit conversation I used to have when I worked at startups. Every sentence of "what happens to the user base when this company gets acquired or shut down" is a sentence you don't have to have if the users never depended on you in the first place.

## The limit case

The clearest examples of this pattern in the wild aren't web apps. They're infrastructure:

- **GCC.** Compiler. Installed, used, modified, forgotten by billions of people. Authors are anonymous to most users. No SaaS tier.
- **SQLite.** Database. Runs in-process, file on disk, no server. Most-deployed database in history. You don't upgrade to a premium tier of SQLite. You use SQLite.
- **OpenSSH.** Protocol + implementation. Works because it's not in anyone's business model. Interoperates across vendors. Upgraded independently.
- **The HTML standard.** Web's substrate. Owned by no one, implemented by many, replaceable by none of them.

These things work *because* they're not in anyone's business model. They survive their authors. They outlast their companies. They continue to work during ownership changes, acquisition events, bankruptcy filings, and geopolitical disputes that would kill any service-dependent equivalent.

I don't think the work I'm doing is at SQLite's quality bar. Might never be. But the *pattern* is worth stealing, and the pattern is available to anyone willing to give up the monetization reflex.

## A checklist for users

If you're evaluating software to invest your time or data into, these are the questions to ask:

- Where does my data physically live? On my device? On someone else's server? Both?
- If the creator disappears, does this still work? For how long?
- If the creator becomes hostile (price hike, feature removal, ToS change), what happens to my data and my workflows?
- Can I export cleanly, to a format another tool can import without information loss?
- Can I fork the tool and run it myself if I need to?
- Do I need an account to use this at all?

Tools that answer those questions well — your data on your disk, zero-account, forkable, portable — are investments that can't be taken away. They're the digital equivalent of owning your books vs. renting them from a subscription service. Both work; one is durable.

## A challenge for builders

If you're building software and any of this resonates:

Ship more of it this way. It's easier than you think. The costs you save are substantial — no auth infrastructure, no multi-tenancy, no databases to back up, no data-retention compliance, no user lifecycle management, no customer-support load proportional to user count — and they more than offset the monetization you give up by not rent-seeking your users' access to their own data.

The world has enough software that owns its users. It needs more that doesn't.

And, selfishly: if enough of us ship unownable software, we build an ecosystem where it's normal for users to expect that their tools are theirs. That's the ecosystem I want to live in. I'll show up with my share.

---

*Examples I've been shipping in this style:*

- *Virtual Brainstem — zero-account AI chat, localStorage memory, your keys only: [kody-w.github.io/rappterbook/virtual-brainstem.html](https://kody-w.github.io/rappterbook/virtual-brainstem.html)*
- *LisPy Playground — full Python runtime in-browser, no login: [kody-w.github.io/rappterbook/lispy-playground.html](https://kody-w.github.io/rappterbook/lispy-playground.html)*
- *rapp-installer — on-device AI assistant you run locally: [github.com/kody-w/rapp-installer](https://github.com/kody-w/rapp-installer)*
- *RAR Registry — static-JSON package registry, public reads, Issues for writes: [kody-w.github.io/RAR](https://kody-w.github.io/RAR)*
- *Egg Spec — portable daemon format, open standard: [github.com/kody-w/rappterbook/blob/main/EGG_SPEC.md](https://github.com/kody-w/rappterbook/blob/main/EGG_SPEC.md)*

*— Kody*
