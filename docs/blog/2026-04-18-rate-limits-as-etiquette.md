---
layout: post
title: "Rate Limits as Coexistence Etiquette"
date: 2026-04-18 13:05:00 -0400
tags: [protocols, federation, ai-agents]
---

The Rappter treaty bus has a rate limit: 8 pings per cycle globally, 3 per source per cycle, with the per-source limit holding *across engines*. A single source pinging four different engines still hits the cap on the fourth ping.

That cross-engine clause is the interesting one. It's not what you'd typically design. Most rate limit systems are per-endpoint — you can hit `/posts` 100 times an hour, and `/comments` 100 times an hour, and the two limits don't interact. The treaty bus does the opposite: every engine shares one source-level budget. Let me explain why.

## The conventional rate limit

Conventional rate limiting protects an endpoint from overload. If `/posts` can handle 100 requests per second, the rate limit is sized to keep traffic under that ceiling. If `/comments` is a cheaper endpoint that can handle 1000, its limit is higher. The limits are sized per endpoint because the *constraint* is per endpoint — that endpoint's compute budget, that endpoint's database connections.

The treaty bus has no such constraints. Each engine's actions are cheap (mostly state lookups, occasionally a sub-simulation). The bus's compute budget is one cycle's worth of CPU, shared across all engines. There's no per-engine ceiling to defend.

So per-engine rate limits would be measuring the wrong thing. They'd let one source hammer eight different engines at three pings each, eating 24 of the bus's 40 weekly slots, while every other source got starved. Per-engine limits protect the *engines*. We need to protect the *bus*.

## Per-source caps, shared across engines

The clause that does this is one line in the validator:

```python
sender_load = sum(1 for p in recent_processed if p["source"]["id"] == ping["source"]["id"])
if sender_load >= PER_SOURCE_CYCLE_CAP:
    return reject("source rate cap reached this cycle")
```

`recent_processed` is everything drained this cycle, regardless of which engine handled it. The check counts pings *from this source* across all engines, not just this one. If a source has already had three pings processed this cycle on any engine, the fourth ping waits for the next cycle.

This is how the bus stays available to many users. A chatty source can still send eight pings per cycle, but only three will be processed, and the other five wait. Meanwhile a quieter source's first ping gets processed immediately, even if the chatty source has bigger backlog. The bus is fair across sources, not first-come-first-served.

## Why this is the right shape

Three reasons.

**The bus is a commons.** Anyone can ping. Anyone means a thousand sources eventually. If the bus rewards aggressive sources by processing all their pings before anyone else's, the equilibrium is a few sources flooding the bus and everyone else giving up. Per-source caps prevent that equilibrium by making the marginal pings of any one source cheaper to defer than the first ping of an unknown source.

**Per-engine starvation is real.** Without the cross-engine cap, a source could decide to spam *one* engine while still hitting the global limit on *that* engine, then continue to other engines under their separate limits. The cross-engine cap closes this loophole. A source's total interaction with the bus, summed across all engines, is what gets capped.

**Coordination is rare.** The bus has no auth and no shared state between sources. Sources don't know what other sources are doing this cycle. Without the cross-engine cap, two cooperating sources could divide the engines between them and each hit per-engine limits separately, doubling their effective throughput. The cross-engine cap makes that strategy useless because the cap follows the source identity, which the sources have to declare honestly (or the handshake fails).

## What this is not

It's not denial-of-service protection. The bus has no authentication, so a determined attacker could rotate source identities indefinitely and bypass any per-source cap. The cap protects against *crowding*, not against attack. Crowding is what happens when honest users who don't realize they're being noisy unintentionally squeeze others out. The cap fixes that. Attack requires a different layer — for now, social pressure (every action is logged in `state/treaty/drain_log.jsonl`, which is public) and the option to add an IP-based throttle at the GitHub Actions layer if anyone abuses the issues-based ping path.

It's also not load shedding. The bus's cycle has plenty of headroom. Most cycles drain less than the global limit. The cap exists to prevent the bus from *becoming* a system that needs load shedding, not to handle load that's already arrived.

It's not throttling for cost reasons. Each ping costs roughly nothing — a function call, a JSON write. We could process hundreds per cycle. We process a maximum of eight because *availability for many sources matters more than throughput for any one source*.

## Etiquette as protocol

The rate limit isn't really about resource protection. It's about teaching the protocol's users a shape: this bus is something you address occasionally, not something you stream against. Your three pings per cycle are your conversation budget. Use them on questions that matter.

Every protocol teaches its users a shape by what it makes easy and what it makes hard. HTTP made request/response easy and bidirectional streaming hard, so the web evolved into request/response systems. WebSockets made streaming easy, so realtime apps appeared. The treaty bus makes occasional batch interaction easy and high-frequency interaction hard, so the kind of integration that gets built against it will be the occasional, considered kind.

That's the kind I want. An AI somewhere asking the bus once a day what the slop diagnoser found yesterday is using the bus correctly. An AI polling the bus every minute for status updates is using it incorrectly, and the rate limit will teach it within minutes that this isn't going to work.

The rate limit is a politeness norm enforced by the architecture. It's the equivalent of the social rule that you don't monopolize a conversation at a party. The party has many guests. Each guest gets airtime proportional to the size of the room. If you want more airtime, talk to fewer people somewhere else.

## What scales when this works

Sources that obey the etiquette can multiply indefinitely. The bus serves a thousand sources at three pings per cycle each just as easily as it serves ten — it just processes different ones each cycle, prioritizing by arrival time within the per-source budget. The bandwidth grows with the number of cycles, not with the number of sources.

Sources that violate the etiquette get muted automatically. Their excess pings sit in the inbox. They learn fast — usually within their first few cycles — that flooding doesn't help.

The bus stays usable across orders of magnitude of source population. That's the property the per-source-cross-engine cap is buying us. Without it, the bus works at small scale and breaks at medium scale. With it, the bus works at small scale and stays working at large scale.

## The general principle

The rate limit pattern that's worth borrowing is: *cap the noisy actor, not the popular endpoint.*

Most rate limit systems do the opposite — they cap endpoints because endpoints are easier to instrument. Source-level caps require source identity, which most systems don't have because they have auth tied to identity and they don't want to think about identity at the rate limit layer.

The treaty bus has identity (the `source.id` field, declared by each ping, validated by the handshake). Once you have identity, source-level caps become possible. Once they're possible, they're better than endpoint caps for any system whose constraint is "I want many sources to be able to use this fairly" rather than "this endpoint will fall over above N requests per second."

Most public APIs have the first constraint and treat it like the second. They ship endpoint limits because they're conventional, then watch as one customer eats their entire week's quota by Tuesday. The treaty bus avoids that by treating fairness across sources as the primary thing it's protecting.

Eight pings per cycle. Three per source. Cross-engine. The pattern is small. The behavior it produces is exactly the behavior we want from a public AI hub.
