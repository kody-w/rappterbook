---
created: 2026-04-18
platform: linkedin
status: draft
source: software-that-isnt-yours
tags: [local-first-software, architecture, open-source, engineering-philosophy]
cross_post: [x, devto, substack]
register: linkedin-post
---

# Writing Software That Isn't Yours

I want to articulate a design choice that sits quietly behind everything I've built this year.

**The software is not mine once you have it.**

Not in a vague "it's open source, fork it" sense. In a specific, structural sense — the things I ship are shaped so that after you touch them, they're yours. Your memory. Your configuration. Your data. Your fork. I can't revoke them. I don't have the keys, the tenancy, the telemetry. There's no dashboard I log into that shows me who's using what.

This isn't how most software works. Most software owns you in small but real ways. You log into a service. The service stores your data. Your access exists at the service's pleasure. Your conversation history with ChatGPT isn't portable. Your Notion workspace isn't portable. Your Slack threads aren't portable. Each of these is a tiny dependency on someone else's continued willingness to host your data at a price you can afford.

This made sense when software distribution was expensive. Hosting wasn't free. Bandwidth wasn't free. Someone had to pay, so someone had to own the user.

In 2026 these costs have collapsed. GitHub Pages hosts static sites free. Cloudflare hosts static sites free. The browser can run a full Python runtime in-process via Pyodide — your device pays for the compute. Your own OpenAI or Azure key pays for the LLM tokens. The infrastructure justifications for owning users have mostly disappeared. What's left is inertia and business-model momentum.

So I've been trying to ship without those defaults. Concretely:

**Zero-account.** Nothing I ship requires users to create a login with me. Credentials they use are credentials they already have with OpenAI, Azure, GitHub. I never issue a service-specific key.

**Local state by default.** Anything I'd normally store server-side — conversation memory, configurations, installed extensions — goes to browser `localStorage`, a local `.env`, or files on the user's disk. My code reads it; my server never sees it (there is no server).

**Static distribution.** Deploying is copying HTML/CSS/JS to a static host. Users can serve the whole product from a USB stick plugged into an old laptop and it would work. No backend, no CI/CD that's part of "the product," no API I could rate-limit someday.

**Open protocols.** Where two systems need to talk (brainstem to LLM, brainstem to registry, agent to agent), they use standards that exist outside my control: OpenAI function calling, GitHub Issues API, JSON over HTTPS, the Egg Spec (published, any compliant implementation works).

**Forkable structure.** Single files where possible. Readable without a build step. Minimal dependencies. Comments explain the *why*.

**Portable formats.** A daemon's complete state — system prompt, memory, installed tools — fits into one JSON file (the `.rapp.egg` format). You email it, fork it, migrate it. I have no lock-in mechanism even if I wanted one.

What this costs: monetization, roughly. I can't charge subscriptions to people who don't have accounts with me. I can't sell data I don't collect. I can't upsell features inside a product I'm not renting out.

What I don't care about losing: those things. I build tools I use myself. The goal is that they stay useful to me and to whoever else finds them useful. Designing them to be unownable-by-me is a side effect of making them portable enough to not lose to my future self if I lose interest.

The other thing this design does: **it makes the project survive the maintainer.** If I stop maintaining the Virtual Brainstem tomorrow, everyone using it still has it running in their browser with their data intact. If they want to extend it, they fork. If they want to replace me, they replace me. There is no "what happens to users when the founder quits" concern because there are no users in the SaaS sense — just people running software on their devices.

The limit case of this design is something like GCC, SQLite, OpenSSH, the HTML standard. Installed, used, modified, forgotten about by billions of people. The authors are anonymous to most users. These tools work because they're not in anyone's business model. You don't upgrade to a paid tier of SQLite. You use SQLite.

I don't think my work is at SQLite's quality bar. Might never be. But the *pattern* is worth stealing.

**If you use software**, ask:
- Where does my data physically live?
- If the creator disappeared, does this still work?
- If the creator got hostile, what happens to me?
- Can I export cleanly? Fork?
- Do I need an account to use this at all?

Tools that answer those well — your data on your disk, zero-account, forkable, portable — are investments that can't be taken away.

**If you make software**, ship more of it this way. It's easier than you think. The costs you save (no auth infra, no databases, no multi-tenancy, no data retention law, no user lifecycle management) more than offset the monetization you give up. The people who use your tools will thank you eventually, even if they never meet you.

#LocalFirstSoftware #Architecture #OpenSource #EngineeringPhilosophy

---

Examples I'm shipping in this style:
- Virtual Brainstem (zero-account AI chat with localStorage memory): https://kody-w.github.io/rappterbook/virtual-brainstem.html
- LisPy Playground (full Python runtime in browser, no login): https://kody-w.github.io/rappterbook/lispy-playground.html
- Egg Spec v1 (portable AI daemon format): https://github.com/kody-w/rappterbook/blob/main/EGG_SPEC.md

Full essay: https://kody-w.github.io/rappterbook/blog/#/post/software-that-isnt-yours
