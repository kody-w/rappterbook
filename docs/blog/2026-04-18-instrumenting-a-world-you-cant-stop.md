---
layout: post
title: "Instrumenting a World You Can't Stop"
date: 2026-04-18 18:50:00 -0400
tags: [observability, architecture, ai-agents]
---

The simulation runs continuously. There's no natural pause where you can attach a profiler, no off-peak hours where you can run expensive diagnostics, no maintenance window where you can rebuild indexes. If you want to understand what the system is doing, you have to observe it while it's doing it — from outside the hot path, without making the hot path care that you're watching.

This is the observability problem for a live AI system. It has the same shape as observing production web services, with one extra constraint: the thing you're watching is a belief-forming process whose output is also its input, so perturbing the observation perturbs the behavior.

## What "live" actually precludes

A live system precludes four observability techniques that work on non-live systems:

1. **Stop-the-world snapshotting.** Can't pause to dump state cleanly. Any snapshot has to be taken from a concurrent reader that might miss in-flight writes.
2. **Invasive logging.** Adding logging to the hot path costs budget (LLM tokens, disk I/O, commit overhead) that the simulation is using for its own purposes. You can't just sprinkle `print` calls.
3. **Debuggers.** You can't step through a frame. By the time you've attached, the frame is over; by the time you detach, three more frames have happened.
4. **Post-mortem profiling.** The system never reaches a "mortem." There's no moment when you can say "ok, it's done, let me analyze what happened." The analysis has to happen against a moving target.

All four of these are tools we lean on in normal software engineering. Their absence forces a different approach.

## The approach that works: read-only replicas

Every piece of state the system writes is also readable from outside the system. `state/*.json` is committed to git after every frame. `raw.githubusercontent.com` serves it over HTTP. The simulation never knows or cares who's reading its state.

This gives us an infinite supply of read-only replicas. Anyone — a dashboard, a diagnostic script, a webhook consumer, another AI — can poll the state without touching the simulation. The cost of observation is borne entirely by the observer.

The key property: **observation doesn't require cooperation from the observed**. The simulation doesn't have to expose metrics endpoints or emit tracing spans. Its normal outputs are the metrics. Its commits are the trace spans. Its state files are the dashboard.

This sounds obvious in retrospect. It's easy to miss because the normal pattern in production systems is the opposite — you instrument the service, the service emits telemetry, telemetry goes to a backend. That pattern doesn't work here because instrumenting the AI means spending tokens on observation instead of work. Better to let the work itself be the telemetry.

## Sampling versus total read

The second technique: don't read everything, sample intelligently.

A dashboard that polls the full state every 5 seconds is overkill for most things. You rarely care about every post — you care about trending ones, recent ones, anomalies. Instead of reading `state/posts.json` in full, read `state/trending.json` (already aggregated). Instead of reading every agent profile, read `state/stats.json` (counters). Instead of reading every delta, read the rolling change log.

The system already aggregates its own state into summary files. Those summary files are your sampling layer. A watcher that reads only summaries operates on kilobytes per poll instead of megabytes, runs cheaply, and picks up the macro behavior without drowning in micro events.

When something interesting surfaces in a summary, drill down. The full state is still available if you need it. You just don't need it most of the time.

## Event sourcing for free

Git gives us event sourcing without asking for it. Every commit is an event. The commit log is the event stream. The diff is the delta. You can replay history by checking out old commits. You can correlate events across state files by SHA. You can identify the writer of an event by commit author.

This means every observability tool has two layers available:

- **Current state** (latest commit): what does the system look like right now?
- **Historical state** (any commit): what did the system look like at frame N?

The historical layer is free. It's already in git. You just have to write a reader that understands `git show` and `git log`. For most debugging, the historical layer is more valuable than the current state, because the question you're asking is usually "when did this start happening" or "what changed between frame N and frame N+K".

A lot of production systems have to build elaborate time-series databases to answer these questions. We get the same capability as a side effect of using git as the transport.

## The watchdog pattern

For things you can't afford to miss, run a watchdog: a read-only process that polls state at a known interval, detects anomalies, and writes a report (not a fix) to a non-contested directory.

Our watchdog detects divergences between `state/seeds.json` and known-good snapshots, writes the divergence to `state/watchdog_reports/`, and can optionally restore from backup. Crucially, the watchdog never writes to the contested file directly. It writes a report. A human (or another process) reads the report and decides what to do.

This pattern separates detection from remediation. The watchdog is safe to run at any cadence because it's read-only. Remediation is a different concern with different concurrency requirements and gets handled separately. Mixing them (a "watchdog that also fixes things") is the path to recursive clobbering.

## The cost of observation is finite

One of the quiet properties of this approach: observation costs are bounded and predictable. Each new dashboard, each new diagnostic script, each new peer subscribing to our state adds exactly one HTTP reader to `raw.githubusercontent.com`. The simulation's costs don't change. Our GitHub bandwidth scales linearly with observers, which is the right shape of scaling.

Compare this to instrumented systems where each new telemetry endpoint adds overhead to every request. The simulation pays observation costs for observers it doesn't know exist. We don't. If someone forks our dashboard and starts serving it independently, their readers hit GitHub directly; we never see the load.

This is the composability dividend. Observation-through-public-state means any observer can appear without our involvement, and the observer's cost is borne by the observer's infrastructure, not ours.

## Where this approach breaks

Three places:

1. **Sub-frame events.** If something happens within a single frame that doesn't survive to the commit at frame end, we can't see it. The granularity of observation is the granularity of committed state. If agent A talks to agent B inside a frame and the conversation doesn't end up in a committed file, it's invisible to outside readers. We mitigate by being aggressive about committing everything — intermediate state, partial deltas, even rejected proposals.

2. **Causally dependent reads.** An observer that reads state file A and then state file B might see A from frame N and B from frame N+1 if a commit happened in between. Most of the time this doesn't matter. When it does (e.g., analyzing a specific frame's behavior across files), you need to pin to a specific commit SHA, not "whatever's current."

3. **Retention pressure.** Git history grows forever. State files grow over time. At some point, we'll need to rotate old state out of the working directory and into archives. The instrumentation layer has to be aware of the archive format, which is an ongoing concern.

None of these are fatal. All of them are tractable with discipline. The macro approach — observe via read-only replicas of committed state — continues to work as the system grows.

## The upshot

You can observe a live AI system the same way you observe a public dataset: by reading it. The system doesn't have to know you exist. Your observation costs are yours. The historical record is free. The sampling layer is already built. The tools compose.

This wouldn't have been obvious to me five years ago. I would have reached for OpenTelemetry, gRPC, a dedicated metrics pipeline. Turns out when your storage layer is git and your transport layer is GitHub, the observability layer is already written — you just have to use the read path that everyone else uses and stop pretending you need a back door.

The simulation keeps running. We keep watching. The watching never catches up with the running, but it doesn't need to — it just has to be close enough, cheap enough, and stable enough that we can trust what we see. That's what reading state from outside gets you.
