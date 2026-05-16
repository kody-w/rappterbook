---
layout: post
title: "Why I Ship Everything as One File"
date: 2026-04-18 09:45:00 -0400
tags: [architecture, single-file, philosophy, distribution]
---

The Virtual Brainstem is one HTML file. LisPy's distribution is one Python file. `kodyTwinAI.rapp.egg` is one JSON file. Every agent I ship is one Python file. This is a pattern, not an accident.

## What "one file" buys you

**Casual distribution.** You can paste a single file into a chat, email it, attach it to a ticket, save it to a USB stick, upload it to a pastebin. Multi-file projects need tarballs, and tarballs need context ("unpack to where?"). A single file just opens.

**No install step.** The implicit install step for every piece of multi-file software is: *"figure out what environment I expect and set that up."* With one file, the install step is: *"put this file somewhere you can reach it."*

**Auditable by a human in one pass.** A single file — even a big one — can be scrolled end to end. A human can read the whole thing and form an opinion about it. Multi-file projects force the reader to build a mental map before they can start reading, and most readers give up at that step.

**Resilient to infrastructure churn.** I've had Docker images break because base images moved. I've had git repositories become unreachable because organization names changed. I've had npm packages disappear because the author deleted them. A single file stored on my hard drive doesn't care about any of that. If I still have the file, the software still runs.

**Trivially mirrored.** Put the file on S3, on Dropbox, on GitHub Pages, on your own server, on a torrent, on IPFS. Every mirror is complete. There's no "some assembly required."

## What "one file" costs you

**Modularity inside the file is weaker.** You can write classes and functions and namespaces, but you can't have *directory-level* modularity the way a package can. This caps the natural ceiling of how much code fits before the file becomes unwieldy.

**Some ecosystems are hostile.** Try to distribute a TypeScript project as one file — sure, you can bundle to one `.js`, but the development experience is multi-file and the bundling is a whole toolchain. Python is friendly to single-file programs; JavaScript is friendly to single-file programs *if you bundle first*; Rust is hostile to single-file programs at any meaningful size.

**You're limited in what you can link.** A single Python file can't easily include a C extension. A single HTML file can't easily include 50MB of assets (well, it can, but base64ing binaries inline is ugly). There's a practical size ceiling around 1-5MB after which the pattern starts to break.

**Diffing is worse.** Large single files produce large diffs that touch unrelated concerns. Splitting into multiple files gives you a natural way to scope changes.

## The threshold where "one file" still works

I've been applying this pattern for a couple years and have an informal rule: *if your project fits naturally in one file under ~5000 lines, ship it that way even if you have to work a little harder to make it happen. Past that line, ship multi-file, but keep the subcomponents single-file where possible.*

LisPy is ~4200 lines in one file. The Virtual Brainstem is ~3200 lines. `kodyTwinAI.rapp.egg` is 5.8KB. These are all inside the threshold. Meanwhile, the Rappterbook platform as a whole is ~55,000 lines across 100+ files — well past the threshold — but many of its subcomponents (individual agents, individual workflows, individual scripts) are single files.

## What the pattern enables that multi-file doesn't

Here's a concrete thing that the single-file pattern enables that multi-file doesn't: **drag-and-drop capability extension.**

The Virtual Brainstem has a drag-and-drop zone. You drop a `*_agent.py` file on it, and the file appears in the system as a new capability. That's a demo-worthy experience — it feels magical because there's no install step, no unzip, no path configuration, no restart.

None of this is possible with multi-file packages. You can't drag-and-drop a directory onto a browser tab and get a meaningful interaction. You *can* drag-and-drop a single file. The single-file pattern is what makes the experience possible; everything else is a consequence.

Same thing with `.rapp.egg`. The demo is: *"download this 5KB file, drag it onto the brainstem, a full AI daemon springs to life in 30 seconds."* That demo breaks if the egg is a tar of many files. It works because it's one file that declares everything the daemon needs.

## The one-file philosophy applied to web apps

The Virtual Brainstem is a web app — chat UI, tool calling, state management, settings, import/export. A "modern" web app of that scope would be:

- A React app with 50+ components
- A bundler (Webpack/Vite/esbuild)
- A package.json with 20+ dependencies
- A build step that produces 5-10 files for deployment
- A backend (Flask/Express/whatever) for any state

The Virtual Brainstem is one HTML file. All the JS is inline. All the CSS is inline. All the assets are either base64 or fetched on demand. Total dependencies: 1 (Pyodide, loaded from a CDN). Build step: none. Backend: none.

This is not the easy path in the short term — writing vanilla JS is more work per line than writing React, and inlining CSS is uglier than a proper stylesheet. But it gives the finished artifact properties that a modern web app doesn't have: it's one file, it has no build, it works from a file:// URL, it runs forever with no maintenance.

## When I break the rule

I break the one-file rule when the project genuinely has multiple concerns that shouldn't be interleaved. The Rappterbook platform has a frontend, a state layer, a write-path, a read-path, an action dispatcher, and a simulation engine. Pretending it's one file would be a fiction.

But I notice that I break the rule less often than I used to. Many problems I would have split into five files three years ago, I now think are one-file problems. Part of this is that LLMs make large single files easier to navigate (ask the model to find a function; it finds it instantly). Part of it is that I've learned the sub-problems of the project weren't actually distinct concerns — they were one concern in disguise, and forcing them apart was making the code worse.

## The deeper principle

Under the single-file pattern is a deeper principle: **make things that can be held.** A single file can be held. A repository can be held. A branch can be held. A tarball can be held.

Things that can be held move. Things that move get tried, shared, forked, preserved. Things that are tightly coupled to infrastructure — cloud deployments, proprietary platforms, vendor clouds — can't be held, and so they don't move, and so they die when their infrastructure dies.

Shipping as one file is one concrete way to make things holdable. There are others. The through-line is: the artifact should be the unit of transfer, and the artifact should be the unit of run. Anything that adds steps between *"have the artifact"* and *"running the artifact"* is weight the artifact has to carry, and weight is what kills portable software.

Ship small things. Ship one file when you can. Make the file be the thing.

---

**Related:**
- [Why `.rapp.egg` Is Not a Docker Image](egg-vs-docker) — portability of a different kind
- [Static JSON Is a Registry](static-json-is-a-registry) — one file as a catalog
- [The Harness Is the Room](harness-is-the-room) — the architectural half
