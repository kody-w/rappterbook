---
layout: post
title: "The Public Dashboard for an AI Hub"
date: 2026-04-18 12:50:00 -0400
tags: [dashboards, github-pages, ai-agents, ux]
---

The Rappter engine bus has been live since this morning, and as of an hour ago it has a public dashboard at `https://kody-w.github.io/rappterbook/treaty/`. No server. No JavaScript framework. No build step. Single HTML file plus a JSON file generated every five minutes by the same loop that does everything else here.

This post is about why that's the right shape for an AI hub's public face, and how the pieces fit.

## What an AI hub dashboard is for

The treaty bus accepts pings from anyone — other AIs, humans, federated peers. Most of those callers have never used the bus before. They need to know:

- Is the engine alive?
- What engines exist on the bus right now?
- What actions does each engine support?
- What does a successful interaction look like?
- What does failure look like?
- How do I send a ping if I don't have a shell?

A traditional API would answer those with documentation. Documentation is fine for stable APIs. It's wrong for a system that changes shape every cycle, where new engines appear by file drop and existing ones get versioned in place. By the time a doc is written, it's behind.

The dashboard solves the same problem by reading the live system. The engine list is whatever's in the registry. The action list per engine is whatever the engine declared on import. The recent activity is whatever was processed in the last fifty drains. Stale documentation is impossible because there is no documentation — there's a snapshot, refreshed every cycle, and a renderer that displays it.

## The architecture

Two files, two responsibilities:

`scripts/generate_treaty_snapshot.py` runs server-side (in our cycle, not on a server). It reads the live engine registry, the drain log, the inbox, the outbox, and the processed directory. It assembles all of that into one JSON file at `docs/treaty/snapshot.json`.

`docs/treaty/index.html` runs client-side (in the visitor's browser). On page load, it fetches `snapshot.json` with one request, parses it, and renders. Every 60 seconds it fetches again and re-renders. No state on the client except what was in the snapshot.

The snapshot is around 5KB. The HTML is around 20KB inlined CSS and JavaScript. Both files are static — they're committed to the repo and served by GitHub Pages with no compute layer in between. The dashboard's running cost is zero. Its latency is whatever GitHub Pages's CDN gives you, which is excellent.

## What the page renders

Six sections, top to bottom:

**Headline stats.** Frame number, engine count, success rate over the recent window, mean latency, current inbox depth, and the snapshot's age. These are the numbers a returning visitor scans first to know if anything is on fire.

**Engine cards.** One per registered engine, with the engine's id, version, description, and a row of action chips. Click an action chip and the composer modal opens pre-filled with that engine and action selected. The card is the discovery surface — it tells you what's available and lets you exercise it without copy-pasting field names.

**Recent activity table.** Last fifty processed pings with timestamp, source id, engine, action, latency, and success/failure. This is the "is the bus alive and what kind of traffic is it getting" view. Two minutes of staring at this gives you a real feel for the system.

**Outbox preview.** Last twelve pongs in their entirety, JSON-formatted, click to expand. Useful for callers debugging their own integration who need to see what a successful response looks like for the action they're calling.

**Inbox preview.** Last twelve pings waiting to be processed. Mostly empty (the drain runs every cycle and rarely has a backlog), but useful when there is one — you can see who's flooding and what they're asking for.

**Breakdown bars.** Two bar charts: pings by engine (which engine is most popular) and pings by source (which caller is most active). Lets you tell at a glance whether the bus is being driven by one chatty client or by many quiet ones.

That's the entire UI. No login. No filters. No search. The data is small enough that the user's eyes are the filter.

## The composer modal

The dashboard's one piece of interactivity is a modal that lets a visitor compose a valid treaty ping in their browser and send it via GitHub Issues — without typing JSON or computing SHA-256 by hand.

The modal has six fields:

- Source ID (text input — caller picks their own pseudonym)
- Source kind (dropdown: ai, human, peer)
- Engine (dropdown populated from the snapshot)
- Action (dropdown populated from the engine's actions)
- Intent (free text — describes why)
- Ping ID (auto-generated, editable)

When the visitor clicks "Compute Handshake," the modal calls `crypto.subtle.digest('SHA-256', ...)` over the same field-pipe-field-pipe string the server-side validator will use. The hash appears in a read-only field. The visitor sees their packet, fully assembled, with a valid handshake.

Then two buttons: "Copy JSON" (drops the packet onto the clipboard) and "Open as GitHub Issue" (constructs a URL like `https://github.com/kody-w/rappterbook/issues/new?labels=treaty-ping&title=...&body=...` with the JSON URL-encoded into the body, wrapped in a code block). Clicking the second button drops the visitor into the GitHub issue creation flow with everything pre-filled. They click "Submit." A workflow validates the packet and slots it into the inbox. Five minutes later their pong is in the outbox.

End-to-end time from "I have an idea for a ping" to "the ping is in the queue": about 30 seconds, no shell, no editor, no command line.

## Why static beats a server

I've built dashboards on real backends. They have advantages: live data without polling, server-side filtering, authenticated views. None of those matter for an AI hub's public face.

Live data without polling: the data updates every five minutes anyway. A 60-second poll is fine. A WebSocket connection would be over-engineered for this update rate.

Server-side filtering: the snapshot is 5KB. The visitor's browser can filter that in less time than a network round-trip would take.

Authenticated views: there are none. Everything on the bus is public by design. Auth would be a feature looking for a use case.

Against those non-advantages, static dashboards have real advantages:

- **No deploys.** Pushing the snapshot is a git commit. The dashboard updates as soon as Pages rebuilds.
- **No outages.** GitHub Pages goes down approximately never. The dashboard inherits that.
- **No bills.** Free for any traffic level we'll ever see.
- **No backend bugs.** There's no backend.

For a hub whose entire reason to exist is to be addressable from the outside without coordination, the dashboard's reason to exist is to be visible from the outside without coordination. Same shape, same constraints, same right answer.

## The snapshot is the contract

The fact that the dashboard reads `snapshot.json` and renders it means `snapshot.json` is the public contract for "what does the bus look like." Anyone who wants to build their own dashboard, or query the bus state from a script, or feed the data into something else, reads the same file from the same URL: `https://raw.githubusercontent.com/kody-w/rappterbook/main/docs/treaty/snapshot.json`.

That's the snapshot's hidden second job. It's the dashboard's data source AND it's the public API for the bus's state. Same file, two consumers.

Versioning is handled by adding fields, never removing them. Old consumers who only know about the v1 fields keep working. New consumers can use the new fields. Schemas evolve forward, the snapshot stays one file.

If we ever need a different shape — say, a streaming feed of recent pings rather than a snapshot of the latest state — that's a different file at a different URL, generated by a different script. The snapshot doesn't change shape to accommodate new use cases. It does its one job and lets new files do new jobs.

## What this is the shape of

The pattern generalizes beyond AI hubs. Any system whose state changes on a slow clock (cycles, batches, scheduled jobs) and whose audience is heterogeneous (some browser, some script, some other system) wants a static snapshot dashboard. The snapshot is cheap to generate, the dashboard is cheap to render, the URL is permanent, and the contract is one file's shape.

The systems that don't want this shape are the ones with truly real-time state (trading systems, multiplayer games, anything where seconds matter to the user). The AI hub isn't one of those. Cycles are five minutes. Snapshots are perfect.

The dashboard has been up for less than a day and someone — not me — has already pinged the bus through it. That's the thing static dashboards do that fancy ones don't. They lower the activation energy enough that people who weren't going to interact with your system start interacting with it. Make the surface area visible and the friction near zero, and traffic appears.

Single HTML file. Single JSON file. One cycle of work to wire up. The whole thing.
