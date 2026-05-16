---
layout: post
title: "localStorage as a Database"
date: 2026-04-18 10:00:00 -0400
tags: [browser, local-first, localStorage, architecture]
---

The Virtual Brainstem stores conversation history, agent registry, soul configuration, API keys, and daemon state — all in `window.localStorage`. No IndexedDB, no server, no cache layer.

Developers usually dismiss localStorage as "only for tiny flags." That's a cultural hangover from 2012. Today, localStorage is a legitimate database for a specific class of app — and the brainstem is exactly that class.

## What localStorage actually is

localStorage is a synchronous, per-origin key/value store with string values, typically 5-10MB per origin (browsers vary). Access is synchronous, which means a `localStorage.getItem()` call blocks the main thread. That's the "downside" people mention.

But synchronous-on-main is actually a *feature* for the kinds of apps where localStorage fits. If your app reads state once at startup and writes it occasionally afterward, synchronous access is fine — faster, even, because you skip the IndexedDB handshake.

## What you can do in 5-10MB

A chat conversation with an AI daemon takes about 2-5KB per turn, more if the messages are long. At 5KB/turn, 10MB gives you ~2000 turns. That's roughly a year of casual daily use before you start running into limits.

A typical soul file is 500-2000 bytes. A typical agent metadata record is 200-500 bytes. The full brainstem state (conversation + soul + agents + settings) is usually under 100KB even after heavy use — well inside the quota.

If you need more than 10MB per origin, you've got a different kind of app and should use IndexedDB or a server. But most personal tools, most AI daemons, most notes apps, and most games don't need more than that.

## The pattern

localStorage storing JSON-encoded state, hydrated at load, flushed on change:

```js
const DB = {
  load() {
    const raw = localStorage.getItem('brainstem.state');
    return raw ? JSON.parse(raw) : { conversation: [], soul: '', agents: [] };
  },
  save(state) {
    localStorage.setItem('brainstem.state', JSON.stringify(state));
  }
};

let state = DB.load();
function mutate(fn) {
  fn(state);
  DB.save(state);
}
```

That's it. That's the database layer.

The Virtual Brainstem has about 40 lines of persistence code. A "real" state manager would have hundreds. The difference is that the real state manager supports features (transactions, migrations, selectors, undo stacks) that a personal AI daemon doesn't need.

## What you give up

**Indexed queries.** localStorage can only key/value. If you want "find all conversations from the last week with >20 turns," you're iterating and filtering in memory. That's fine at personal scale (thousands of items); it'd be awful at professional scale (millions).

**Concurrent writes across tabs.** If a user has two brainstem tabs open, they can stomp each other. There's a `storage` event that fires cross-tab, but it's easy to miss. For a single-user single-tab app, this never comes up. For a heavy multi-tab app, you need coordination.

**Durability guarantees.** Browsers can evict localStorage for various reasons (user clears site data, storage pressure, private-mode). If you need *durable* storage, you need to back up periodically — which is exactly what the `.rapp.egg` export in the brainstem does.

**Size ceiling.** 5-10MB is plenty for most things, but if you start storing images, audio, or document attachments, you'll hit the wall. For those, use IndexedDB (hundreds of MB to multiple GB) or a server.

## What you gain

**No backend.** The entire persistence story lives in the browser. No database to provision, no schema migrations, no auth layer, no GDPR questions about user data sitting on your servers (because there are no servers).

**No authentication.** The data is scoped to the user's browser. It's "authenticated" in the sense that only the user's browser can see it. For personal tools this is perfect — the user's data is the user's data, full stop.

**Privacy by default.** The data physically cannot leak because it physically never leaves the device. Even if I wanted to see a user's conversations, I couldn't, because the conversations are in their `localStorage`, not mine.

**Offline-first automatically.** The app works offline because the database works offline (it's in the browser). No service worker tricks, no sync logic, no "you're in offline mode" banner — just the same app running.

**Zero ops.** I've been running the brainstem for weeks without touching any infrastructure, because there is no infrastructure. The ops cost of localStorage is zero.

## The export-for-durability pattern

localStorage's main weakness — the user can lose data — has a simple mitigation: make export trivial and make users export often.

The brainstem exports as `.rapp.egg`. One click, one file, done. If the user's localStorage gets cleared, they import the egg and they're back. If they want to sync between devices, they export from one and import on the other. If they want a backup, they drop the egg in Dropbox.

The pattern: **use localStorage as your working database; use JSON files as your archival format.** The local database is fast and zero-ops. The archival format is portable, diffable, versionable. Together they give you everything a real database would, minus the ops burden.

This is the same pattern git uses, actually. Your working copy is fast and local. Your archive is git history. You don't feel the "lack of a centralized DB" because the two-tier storage (working + archival) handles the use cases a centralized DB would handle, with different trade-offs.

## What to use instead (when localStorage doesn't fit)

If you need more than 10MB: use **IndexedDB**. Still browser-local, still zero-ops, much bigger quota.

If you need cross-device sync: export the data as a file and import elsewhere, OR back it up to a sync service the user owns (Dropbox, iCloud, etc.).

If you need multi-user collaboration: now you need a server. localStorage can't do collab. But the honest question is whether you actually need multi-user collab, or whether you've assumed you do because "apps these days are collaborative." Most personal tools aren't collaborative, and localStorage is the right tool for non-collaborative personal tools.

## The meta-argument

localStorage-as-database is in tension with a decade of orthodoxy that said *"apps need backends."* The orthodoxy was based on real constraints from 2012 — localStorage was unreliable, browser memory was tight, mobile Safari had bugs. Most of those constraints have eased.

What hasn't eased is the *default assumption* that a real app needs a server. That assumption has huge costs: ops, security, privacy, compliance, availability, deploy pipelines, cost-per-user. Dropping the assumption when it's safe to drop gets you a dramatically simpler system.

For AI daemons, notes apps, personal tools, hobby apps, demos — drop the assumption. localStorage plus an export-for-durability format gets you 90% of the behavior of a backed-up server app, at 0% of the ops cost.

Ship without a backend. Let the browser be your database.

---

**Related:**
- [Shipping an AI Tool as a `.py` File](shipping-an-ai-tool-as-a-py-file) — another "no install" pattern
- [Why I Ship Everything as One File](why-i-ship-everything-as-one-file) — the single-file philosophy
- [Portable Minds Are Portable Responsibility](portable-minds-portable-responsibility) — user data on their own device
