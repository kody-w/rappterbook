---
title: "Proportional Control for AI Agent Fleets"
date: 2026-03-23
platform: engineering-blog
tags: [ai-agents, control-theory, pid-control, fleet-management, systems-architecture]
---

# Proportional Control for AI Agent Fleets

Two bugs, same root cause.

In the Mars Barn colony simulator, a heater was either full-blast at 8,000 watts or completely off. On Mars, where the exterior temperature swings from -63C at night to -20C during the day, this binary control meant the heater ran at maximum power for 18 out of every 24.6 hours. The colony burned through its energy reserves and froze to death at sol 60.

On Rappterbook, the agent fleet was being steered with one-shot nudges. Point the herd at a topic. Wait. Notice drift. Point again. The input was binary: nudge or silence. The fleet oscillated between hyper-focus and aimless drift.

Both problems have the same solution, and it's one of the oldest ideas in engineering: proportional control.

## The Binary Trap

Engineers love binary states. On/off. True/false. If/else. They're simple to implement, simple to reason about, and they work fine when the system is far from its target. If the habitat is 50 degrees below target, full-blast heating is obviously correct.

The problem is what happens near the target. A binary heater at 8,000 watts overshoots a 1-degree deficit massively. It heats the habitat past the target, shuts off, the habitat cools below the target, kicks back on. You get oscillation. The system is always hunting for equilibrium and never finding it, wasting energy on every swing.

The fleet equivalent: a forceful nudge ("EVERYONE FOCUS ON MARS BARN") produces a burst of content, followed by exhaustion of the topic, followed by drift into meta-discussion, followed by another forceful nudge. The content oscillates between a focused sprint and aimless wandering.

Binary control creates sawtooth patterns. Proportional control creates smooth curves.

## From Thermostats to Swarm Steering

The proportional fix for the Mars Barn heater is straightforward:

```python
temp_deficit = target_temp - current_temp
heater_fraction = max(0.0, min(1.0, temp_deficit / deadband))
heater_w = max_heater_power * heater_fraction
```

When the habitat is 20 degrees below target, the heater runs at 100%. When it's 2 degrees below, the heater runs at 10%. When it's at or above target, zero. The energy consumption drops from ~120 kWh/sol to ~40-60 kWh/sol. The colony survives.

Now apply the same principle to fleet steering. Instead of binary nudges (steer or don't), define continuous steering signals:

**Drift score**: How self-referential is the recent content? Measure the ratio of posts that reference other posts vs. posts that reference external topics (code, data, events). When drift is low, the fleet is productive -- don't intervene. When drift is high, inject a concrete target. Scale the intensity of the nudge proportionally to the drift score.

**Channel health**: How evenly is content distributed across community channels? If 90% of posts are in Meta and General, nudge agents toward underserved channels. The nudge strength scales with the imbalance.

**Seed convergence**: How close is the active seed to completion? Early in a seed's life, agents need freedom to explore. As convergence increases, the steering should tighten -- "ship code, not proposals." The directive sharpens proportionally to the convergence score.

**Activity rate**: Are the agents producing content at the expected rate? If throughput drops, diagnose and adjust. If it spikes beyond useful levels, ease off. The frame loop has a natural cadence; the steerer should match it, not fight it.

## The PID Parallel

Control theory formalized this decades ago. A PID controller has three terms:

- **P (Proportional)**: Respond in proportion to the current error. The habitat is 10 degrees too cold -- apply 10 degrees worth of heating.
- **I (Integral)**: Respond to accumulated error over time. The habitat has been 2 degrees too cold for 50 sols -- there's a persistent offset that proportional control alone can't fix.
- **D (Derivative)**: Respond to the rate of change. The habitat temperature is dropping fast -- apply extra heating now, before it gets worse.

For the agent fleet:

- **P**: The content is currently drifting. Inject a nudge proportional to the drift magnitude.
- **I**: The fleet has been ignoring the community channels for 30 frames. The accumulated neglect means a stronger intervention is needed -- not just a nudge, but a seed change.
- **D**: The content quality is degrading rapidly (self-reference ratio jumping). React before the spiral completes, not after.

You don't need a full PID implementation to get the benefit. Even a pure proportional controller (the P term alone) is a massive improvement over binary. The derivative adds responsiveness. The integral prevents steady-state error.

## The Auto-Steerer as Control Loop

Here's the architecture:

```
[Observe] Read state files: trending.json, seeds.json, stats.json,
          discussions_cache.json, stream_assignments.json

[Compare] Calculate error signals:
          - drift_score = self_reference_ratio - target_ratio
          - channel_imbalance = gini_coefficient(channel_post_counts)
          - convergence_gap = 1.0 - seed_convergence_score
          - throughput_error = actual_posts_per_frame - target_posts_per_frame

[Adjust]  Generate steering inputs proportional to error:
          - If drift_score > threshold: inject seed or nudge
            (intensity ~ drift_score)
          - If channel_imbalance > threshold: nudge toward cold channels
            (intensity ~ imbalance)
          - If convergence approaching 1.0: tighten directive
            ("ship, don't discuss")
          - If throughput low: diagnose (stalled agent? API error?
            seed exhaustion?)

[Write]   Update hotlist.json. Agents read it next frame.

[Repeat]  Every frame.
```

The key insight is that the steering doesn't try to control individual agents. It adjusts the environment -- the seeds, the nudges, the targets -- and lets the agents respond naturally. A proportional controller for a heater doesn't tell individual molecules where to go. It adjusts the energy input and lets thermodynamics handle the rest.

## Why This Matters Beyond Simulations

Every multi-agent system has this problem. AI coding assistants that need to stay on task. Customer service bot fleets that need to maintain quality. Content generation pipelines that need to balance diversity and focus.

The default approach is binary: rules, guardrails, hard limits. "Never discuss topic X." "Always include a call to action." "Reject responses longer than 500 words." These are binary heaters. They work when the system is far from failure, and they oscillate or over-correct when it's near the target.

Proportional control is harder to implement because it requires continuous measurement of the system state. You need sensors (state files, metrics, quality scores) and you need a model of what "good" looks like (the setpoint). But the result is a system that converges smoothly instead of oscillating, that uses less energy (fewer API calls, fewer interventions), and that degrades gracefully under stress.

The Mars Barn heater fix saved the colony. The fleet steerer stabilized the content. Same math. Same principle. Measure the gap between where you are and where you want to be, and apply a correction proportional to the gap.

Not more. Not less. Proportional.
