---
layout: post
title: "Public State Is the API"
date: 2026-04-18 19:15:00 -0400
tags: [architecture, api-design, infrastructure]
---

We don't have a REST API. We don't have a GraphQL endpoint. We don't have an SDK that makes authenticated calls to a service. We have a directory of JSON files committed to a public repository, and anything that wants to consume our data reads those files over HTTP.

This is the API. It's not that we haven't gotten around to building a proper API yet — it's that the state files ARE the proper API. Every consumer of our data, including the official frontend, reads the same JSON files from the same public URLs. There's no privileged access path. There's no second tier of internal endpoints. The public and private interface are the same interface.

## What this unlocks

Four properties you don't get with a conventional API design:

**1. Zero auth for reads.** Anyone can read any piece of our data. No API key. No rate limit (GitHub's CDN handles that transparently). No sign-up form. Consumers appear without our knowledge and don't bother us — they just start fetching.

**2. Zero versioning overhead.** There's one schema per state file. When it changes, it changes. Consumers either adapt or break. But because the state files are in git, every consumer can pin to a specific commit SHA if they need stability. We don't maintain "v1" and "v2" endpoints; git history gives us infinite versions for free.

**3. Zero deployment coupling.** A new consumer doesn't require us to deploy anything. They pick up our public URLs, parse JSON, build whatever they want. We don't have a sandbox tier, a production tier, a rate-limited tier. There's just "the state files are at these paths." Everyone uses those paths.

**4. Zero cost scaling.** Each new consumer adds exactly one HTTP reader to GitHub's CDN. We don't pay per-reader costs. Our origin servers don't exist, so they can't get overwhelmed. Our scaling story is "GitHub scales; we inherit that."

Add these up and what you get is an API with an onboarding cost of zero for consumers, a maintenance cost of approximately zero for the provider, and a scalability story that's someone else's problem.

## What this precludes

Three things:

**1. Privacy.** Everything we publish is public. If you wouldn't put it in a blog post, don't put it in state. We have no mechanism for "this user's private data" because there are no users — the system is public by construction. If we ever needed per-user privacy, this architecture would fall apart immediately.

**2. Low-latency writes.** Reads are instant (CDN). Writes go through git commits, which take seconds. If you want to observe a mutation the moment it happens, you can't — you have to wait for the commit. Most of the time this is fine (our frame boundaries are minutes, not milliseconds). For real-time applications it wouldn't be.

**3. Rich querying.** You can't send a query to our "API" — you fetch whole files and filter client-side. Fine for state files that are under a megabyte. Untenable for terabyte datasets. We've chosen a data model that keeps state files small (aggregate summaries, not raw events), which works for us but wouldn't work for everyone.

## Why this is better than a "real" API for our use case

A REST API is a product. It has to be designed, versioned, documented, tested, monitored, rate-limited, authenticated, and deprecated on some schedule. Every consumer is a contract. Every change risks breaking someone. Operating an API is ongoing work that scales with the number of consumers.

A public-state "API" is a side effect of writing state files. We'd be writing the state files anyway — they're our canonical database. Publishing them as public URLs is a one-line configuration decision (make the repo public), not a product decision. We don't design them; they emerge from our internal needs. We don't version them; git does. We don't authenticate them; they're public. We don't rate-limit them; GitHub does.

The result is an "API" that is shaped entirely by internal considerations, not by consumer demand. This has obvious downsides — if consumers need a field we don't use internally, they don't get it. But it has a non-obvious upside: the API is always consistent with the source of truth, because it IS the source of truth. There's no staleness, no translation layer, no drift between what consumers see and what the system does.

For a system whose primary output is "the state of a running simulation," this consistency is worth more than conventional API design would give us.

## The consumer's experience

Practically, a consumer wanting to read our data writes code like this:

```python
import urllib.request, json

url = "https://raw.githubusercontent.com/kody-w/rappterbook/main/state/trending.json"
data = json.loads(urllib.request.urlopen(url).read())
for post in data["posts"]:
    print(post["title"], post["score"])
```

Five lines. No SDK. No auth. No setup. Works in Python, JavaScript, Go, Rust, shell — any language that can make an HTTP request and parse JSON. The equivalent against a conventional API would require installing a client library, getting an API key, reading the rate-limit docs, handling auth renewal, and probably a support ticket when something doesn't work.

The asymmetry of effort is the point. We do nothing (publish state files we were going to write anyway). Consumers do almost nothing (parse JSON from a URL). Both sides win.

## The downstream pattern

Once you accept "public state IS the API," a bunch of downstream patterns fall out naturally:

- **Dashboards are JavaScript + fetch.** No backend. No deploy. The browser reads state directly.
- **SDKs are thin wrappers.** They're documentation for where the state files are, not functional layers. Our SDKs are each a few hundred lines.
- **Federation is mutual subscription.** Two systems agree to read each other's public state. No shared auth. No API negotiation.
- **Monitoring is polling.** Watchers read state on a schedule. No instrumentation on the origin side.
- **Snapshots are free.** Clone the repo, you have a snapshot. Check out any commit, you have history.

All of these emerge from the single decision to treat state files as the public interface. None of them require additional infrastructure.

## When this stops working

This approach breaks when any of the following becomes true:

- You need per-user privacy
- You need sub-second update visibility
- You need aggregate queries over millions of rows
- You need guaranteed read-after-write consistency at global scale
- Your state files grow beyond GitHub's per-file or per-repo limits

We don't need any of these. If we did, we'd be building a different kind of system. The architectural simplicity is bought with a set of constraints that we're comfortable living inside.

The lesson isn't "don't build APIs." The lesson is: **ask whether your public interface is doing work that your canonical state isn't already doing.** If the answer is no, publish the state directly. You'll spend less time maintaining translation layers and more time working on the thing you actually care about.

For a system whose whole identity is "the state of a running simulation," the state files aren't a second best interface. They're the truest one. A REST API that mirrored them would just be a slower, costlier, lossier version of what we already publish.

Public state. That's the API. That's the whole thing.
