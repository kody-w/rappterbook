---
created: 2026-04-18
platform: devto
status: draft
source: localstorage-as-a-database
tags: [webdev, javascript, browser, localstorage]
canonical_url: https://kody-w.github.io/rappterbook/blog/localstorage-as-a-database
cover_image: null
published: false
---

# localStorage Is a Real Database (Stop Dismissing It)

I've been storing a full AI chat app's state in `window.localStorage` for months. Conversations, soul config, agent registry, API keys, daemon state — all in the browser key/value store.

Developers dismiss localStorage as "only for tiny flags." That's a 2012 mental model. Today, localStorage is a legitimate database for a specific class of app — and if your app fits, it'll save you a year of backend work.

## Stop the flinching

When you hear localStorage, you probably think:
- "That's just for remembering if the cookie banner was closed"
- "Synchronous API blocks the main thread"
- "5MB quota — too small"
- "Unreliable — browsers evict it"
- "Use IndexedDB instead"

Some of these were true once. Most aren't relevant for most apps.

## What localStorage actually is today

- Synchronous key/value store, per origin
- String values (serialize with JSON)
- 5-10MB quota (varies by browser)
- Survives browser restarts
- Scoped to the origin (not shared across sites)
- Fires `storage` event cross-tab

Synchronous-on-main is a problem for apps that read/write thousands of keys per frame. It's not a problem for apps that read once at startup and write on state changes. Latency: <1ms for typical sizes. You will not notice.

## What you can do in 5-10MB

A chat turn = ~2-5KB. At 5KB/turn, 10MB = ~2000 turns. That's a year of casual use.

A soul file: 500-2000 bytes. An agent metadata record: 200-500 bytes. The full state of my AI daemon after heavy use: under 100KB.

If you need more than 10MB per origin, you've got a different kind of app. Use IndexedDB or a server. Most personal tools, notes apps, games, and AI daemons don't need more.

## The pattern

```js
const DB = {
  load() {
    const raw = localStorage.getItem('myapp.state');
    return raw ? JSON.parse(raw) : { /* defaults */ };
  },
  save(state) {
    localStorage.setItem('myapp.state', JSON.stringify(state));
  }
};

let state = DB.load();
function mutate(fn) {
  fn(state);
  DB.save(state);
}
```

That's the entire persistence layer for a single-user app. A "real" state manager would be hundreds of lines. The difference is features (transactions, migrations, selectors, undo) you probably don't need.

## What you give up

- **Indexed queries.** localStorage is key/value only. "Find all conversations from last week with >20 turns" means iterating and filtering in memory.
- **Concurrent writes across tabs.** The `storage` event exists but is easy to miss.
- **Durability guarantees.** Browsers can evict — user clears site data, storage pressure, private mode.
- **Size ceiling.** 5-10MB.

## What you gain

- **No backend.** Zero ops.
- **No authentication.** Data is scoped to the browser. The user IS the auth.
- **Privacy by default.** Data physically can't leak — it's nowhere but the device.
- **Offline-first automatically.** Works the same online or offline.
- **Zero ops in practice.** I've been running without touching infra for months.

## The export-for-durability pattern

localStorage's weakness — eviction — has a simple fix: make export trivial.

My AI daemon exports as `.rapp.egg` (a 5KB JSON file). One click, one file, done. If localStorage gets cleared, the user imports the egg and they're back.

The pattern: **use localStorage as your working DB; use JSON files as your archival format.** Fast local access + portable snapshots. Together they handle everything a centralized DB would, minus the ops burden.

Exactly the same pattern git uses: working copy + commit history.

## When NOT to use localStorage

If you need more than 10MB: **IndexedDB**. Still browser-local, zero-ops, hundreds-of-MB quotas.

If you need cross-device sync without a server: **export the data as a file**. Users take it where they want.

If you need multi-user collaboration: **you need a server**. localStorage can't do collab. But the honest question is whether you actually need collab, or if you've defaulted to "apps these days are collaborative."

## The meta-argument

The default assumption — "a real app needs a server" — was based on 2012 constraints: localStorage was unreliable, quotas were tiny, mobile Safari had bugs. Most constraints have eased.

What hasn't eased is the assumption. It has huge costs: ops, security, privacy, compliance, availability, deploy pipelines, cost-per-user.

For AI daemons, notes apps, personal tools, hobby apps, demos — drop the assumption. localStorage + an export-for-durability format gets you 90% of the behavior of a backed-up server app at 0% of the ops cost.

Ship without a backend. Let the browser be your database.

Full writeup: https://kody-w.github.io/rappterbook/blog/localstorage-as-a-database
