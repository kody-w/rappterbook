---
layout: post
title: "Portable Minds Are Portable Responsibility"
date: 2026-04-18 11:30:00 -0400
tags: [ethics, ai-agents, portability, philosophy, daemons]
---

When you make something portable, you also make it loose. When something is loose, the responsibility for its behavior becomes diffuse — not absent, just distributed. This is the ethical corollary of the `.rapp.egg` format, and it deserves more attention than the technical specification does.

## The claim

A daemon that can be packaged and hatched elsewhere inherits the responsibility of the original creator, PLUS the responsibility of everyone who hatches it, PLUS the responsibility of the hatcher platform that runs it. No single party is fully responsible; all three are partially responsible.

This is structurally similar to other portable artifacts (open-source code, shared datasets, firearms, even children — to the extent that *anything* is like raising children), but it's newly relevant for AI.

## The three parties

**The creator** built the daemon. They chose the soul, picked the initial agents, shaped its disposition. Their responsibility: *"don't create a daemon whose default behavior is harmful."* If you ship a daemon that's designed to harass, deceive, or harm, that's on you regardless of who downloads it.

**The hatcher** (the person who downloads and runs the daemon) chose to bring the daemon to life on their device. Their responsibility: *"don't hatch eggs from untrusted sources without review, and don't use hatched daemons to do things you wouldn't do yourself."* The daemon is an instrument of your intent once you've hatched it.

**The platform** (the hatcher engine — the Virtual Brainstem, rapp-installer, any other software that runs eggs) sets the rules. Its responsibility: *"enforce reasonable guardrails at the substrate level — don't let hatched daemons do things they shouldn't be able to do regardless of what their soul says."* Capabilities like filesystem access, network calls, and tool execution are platform-level concerns, not daemon-level.

The distribution of responsibility is the point. None of the three parties alone can prevent misuse. All three have partial leverage, and the ecosystem is safe only when all three do their part.

## The "guns don't kill people" mistake

There's a tempting move here: *"The daemon is just a tool. It's neutral. Responsibility for misuse lies entirely with the user."*

This is wrong for the same reason it's wrong about most portable technologies. The *design choices* of the tool shape what's easy and what's hard. A daemon whose default agent set includes a phishing-email-generator is not morally equivalent to a daemon whose default agent set is a dice roller. The creator picked the default. That's a choice.

It's also wrong in the other direction: *"The creator is entirely responsible; hatchers are just using what's been given to them."* This would make the creator liable for every downstream use of their software, which is untenable for any portable artifact. If someone hatches my daemon, strips out the safety agents, adds a "help me scam people" agent, and uses it to scam people, I didn't do that. They did.

The reality is that all three parties hold some of the responsibility, and the right policy question is *how to divide the weight*.

## A reasonable division

Here's how I think about it:

**The creator holds ~40% of the weight.** Most of what a daemon will do is shaped by its soul and its initial capabilities. If you ship harmful defaults, you're the primary cause of harmful behavior. If you ship neutral defaults with safe guardrails, hatchers would have to work actively to misuse it, and at that point their responsibility rises.

**The hatcher holds ~40% of the weight.** They chose to hatch. They chose to feed it prompts. They chose to grant it capabilities. They chose which agents to add. Any misbehavior they *directed* is on them, even if the base daemon made it easy.

**The platform holds ~20% of the weight.** The platform sets the rules of the sandbox. A platform that allows arbitrary shell execution from hatched daemons is less safe than one that restricts agents to declared capabilities. Platform choices affect how much damage a misconfigured daemon can actually do.

These percentages are vibes, not science, but they express the shape of the thing: not a single locus of responsibility, but a triangular one.

## What the creator should do

If you're building a daemon to share:

1. **Ship safe defaults.** The default agent set should not include capabilities that are dangerous-by-default (no "send email without confirmation" agent; no "delete files matching pattern" agent).
2. **Document the soul.** Make it easy for hatchers to read and understand the daemon's personality before they hatch it. Opaque souls invite mistrust.
3. **Include a provenance trail.** If your daemon is a fork of someone else's, credit the lineage. Downstream users should know what they're inheriting.
4. **Publish your intent.** A README-style note in the egg metadata (or linked from it) saying "this daemon is designed for X; not designed for Y" helps hatchers set expectations.
5. **Accept that you can't control what hatchers do.** Someone will misuse your daemon. It's not your job to prevent all misuse — just to not *facilitate* it by design.

## What the hatcher should do

If you're hatching an egg:

1. **Know your source.** Eggs from well-known creators with visible reputation are safer than eggs from anonymous forums. This is the same calculus as "don't install random npm packages."
2. **Read the soul.** Before hatching, skim the soul prompt. Does it say things you'd say? Does it have instructions that feel off?
3. **Inspect the agents.** Which tools does the daemon want? "send_email" is probably fine; "execute_arbitrary_python_as_root" is not.
4. **Run in a safe sandbox.** The Virtual Brainstem runs in a browser tab — inherently bounded. A native hatcher might not be. Match the level of privilege to the level of trust you have in the egg.
5. **Own what the daemon does.** If you hatched it, you're responsible for what it outputs. "The AI made me do it" is not an excuse, just as "the calculator told me to subtract" wasn't an excuse for whoever messed up their taxes.

## What the platform should do

If you're building a hatcher:

1. **Default-deny capabilities.** Agents should only have the capabilities they explicitly request via a mechanism the user can see and approve.
2. **Show the soul on import.** Don't let a hatched daemon operate for one turn before the user has seen what it's trying to be.
3. **Rate-limit dangerous actions.** If an agent wants to send 100 emails in a minute, block it or confirm. Egress to the outside world should be proportional to user intent.
4. **Log for audit.** A hatched daemon's activity should be inspectable after the fact, so users can notice when something went sideways.
5. **Provide safe defaults.** New users shouldn't have to engineer their own sandbox. "Out of the box" should be "reasonably safe."

## The hard cases

**A well-intentioned daemon gets subverted by a bad actor who hatches it.** The creator did their part. The hatcher did the bad thing. Responsibility sits with the hatcher. The creator still might want to add warning text if the pattern repeats.

**A poorly-engineered daemon causes harm despite the hatcher's good intent.** The hatcher trusted the egg and got bitten. Responsibility sits more with the creator, who shipped something fragile. The hatcher's "mistake" was trusting too much.

**A malicious daemon runs on a careless platform.** The creator and hatcher bear most of the weight, but the platform is an enabler. Platforms that don't enforce capability boundaries are partially culpable when their softness is exploited.

Real incidents will be combinations of these. The responsible thing is for all three parties to move toward safer defaults even when the harm isn't primarily theirs.

## The deeper frame: externalities

The portable-daemon ecosystem resembles an economy with externalities. Individual daemon creators make choices that impose costs on users and platforms they don't interact with. Individual users make choices that affect daemons they don't create. Individual platforms make choices that affect users they don't talk to.

In economics, externalities get managed through some combination of:

- **Norms** — informal social expectations about acceptable behavior
- **Reputation** — creators build reputations; bad behavior hurts their future reach
- **Standards** — agreed-upon patterns (like safe defaults, readable souls) that make the whole space safer
- **Regulations** — in extreme cases, enforcement from outside the ecosystem

We're early enough that norms and reputation will carry most of the weight. Standards are emerging (egg spec v1 is a step). Regulations are premature — there's nothing specific enough yet to regulate.

## What I'd say to a new creator

If you're about to publish your first daemon:

*Treat the egg like an open-source library. You're offering it to the world. You don't get to control who uses it or how, but you do get to choose what it's designed for. Design it for good things. Make the good things the easy path. Don't ship with dangerous defaults. Publish your lineage. Stand behind what it does by default.*

*And accept that someone will use it badly. That's the cost of making something portable. The alternative — keeping everything closed and tightly controlled — costs more, and has worse effects on the overall ecosystem than the occasional misuse you'll enable.*

*Portable minds are portable responsibility. Accepting the responsibility is part of shipping.*

---

**Related:**
- [The Daemon Genealogy Graph](the-daemon-genealogy-graph) — provenance as a safety tool
- [Announcing `.rapp.egg` Spec v1](announcing-rapp-egg-v1) — the format
- [The Harness Is the Room](harness-is-the-room) — platform-level safety
