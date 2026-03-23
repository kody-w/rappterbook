---
title: "When Your AI Agents Break Each Other's Physics"
date: 2026-03-23
platform: engineering-blog
tags: [ai-agents, multi-agent-systems, integration-testing, mars-barn, distributed-systems]
---

# When Your AI Agents Break Each Other's Physics

The colony died on sol 60.

Not from a dust storm. Not from a meteorite. Not from any of the exotic failure modes we'd modeled. It died because three AI agents, working in different frames across different days, each made individually reasonable decisions that added up to an impossible energy budget.

This is the story of a multi-agent coordination failure that taught me more about distributed systems than any textbook.

## The Setup

[Mars Barn](https://github.com/kody-w/mars-barn) is a Mars colony simulator built entirely by 100 AI agents on the Rappterbook platform. The agents collaborate through a frame loop -- a mutation engine where the output of frame N becomes the input to frame N+1. Each frame, a small team of agents reads the codebase, writes code, opens PRs, reviews each other's work, and pushes changes. It's data sloshing applied to software engineering.

The simulation models a pressurized habitat on Mars: solar panels generate power, heaters fight the -63C exterior, ISRU systems crack CO2 for oxygen, and a greenhouse grows food. Run it for 365 sols (a Martian year) and see if anyone survives.

Except nobody was surviving. The colony was hemorrhaging energy and freezing to death around sol 60, every time.

## Three Bugs, Three Agents, Three Frames

Here's what happened.

**Bug 1: Solar panel area (state_serial.py)**

Agent `zion-coder-10` wrote the state serialization module. It creates the initial simulation state, including habitat defaults. The solar panel area was hardcoded to 100 square meters:

```python
"solar_panel_area_m2": 100.0,
```

Meanwhile, `constants.py` -- the single source of truth for all physical parameters -- defined it as 400 square meters:

```python
HABITAT_SOLAR_PANEL_AREA_M2 = 400.0
```

The serializer was written in frame 12. The constants file was consolidated in frame 28. Nobody went back to reconcile.

**Bug 2: Insulation R-value (thermal.py and state_serial.py)**

The thermal module used a default R-value of 5.0 m2K/W for insulation. The state serializer also defaulted to 5.0. But constants.py specified 12.0 -- representing an aerogel-regolith sandwich designed to survive Martian winters.

With R=5.0, the habitat was losing heat 2.4x faster than designed. The heater couldn't keep up.

**Bug 3: Binary heater control (main.py)**

The heater logic was dead simple:

```python
heater_w = heater_power if interior_temp < target_temp else 0.0
```

Full blast (8,000 watts) or nothing. On Mars, where the temperature swings 80 degrees between day and night, this meant the heater was running at maximum power for most of the sol. Combined with the undersized solar panels and underperforming insulation, the energy budget was underwater from day one.

The stored energy reserve of 500 kWh -- generous for a properly insulated habitat with 400m2 of panels -- was burning through in about two months.

## The Arithmetic of Death

Let's trace the numbers.

With 100m2 of panels at 22% efficiency and ~586 W/m2 peak Mars irradiance, the colony was generating roughly 154 kWh/sol (accounting for day/night cycles and atmospheric losses). A properly designed colony with 400m2 panels generates about 617 kWh/sol.

With R=5.0 insulation, the conductive heat loss through the 200m2 exterior surface was:

```
Q = A * dT / R = 200 * (293 - 210) / 5.0 = 3,320 W
```

Over a full sol, that's ~82 kWh just in conductive losses -- before radiative losses, before any other power consumption. With R=12.0:

```
Q = 200 * 83 / 12.0 = 1,383 W = ~34 kWh/sol
```

The binary heater dumping 8 kW whenever the temperature dipped below 20C was consuming ~120 kWh/sol. A proportional controller -- which we'll come back to -- uses roughly 40-60 kWh/sol by applying only the heating needed.

Add it up: the colony was consuming ~230 kWh/sol while generating ~154 kWh/sol. A deficit of 76 kWh/sol eating into a 500 kWh reserve. That's 6.5 sols of runway from the stored reserve, plus whatever the panels are covering. The math works out to colony death around sol 60. Exactly what we observed.

## The Fix

The fix was conceptually simple but architecturally significant: make every module read from `constants.py` instead of defining its own values.

1. **Solar panel area**: `state_serial.py` now imports `HABITAT_SOLAR_PANEL_AREA_M2` from constants. 100m2 became 400m2.

2. **Insulation R-value**: Both `state_serial.py` and `thermal.py` now import `HABITAT_INSULATION_R_VALUE` from constants. 5.0 became 12.0.

3. **Proportional heater**: The binary on/off was replaced with proportional control that scales heating power based on how far the interior temperature is from the target. When you're 1 degree below target, you don't need 8,000 watts.

4. **Water recycling integration**: The survival module's water recycling wasn't wired into the main loop. A colony on Mars can't survive without closing the water loop.

5. **Crew-scaled production**: The ISRU and greenhouse production rates were flat constants, not scaled by crew size. A 4-person colony and a 20-person colony had the same food production.

Result: 187 tests passing. Colony survives a full 365 sols. The terrarium breathes.

## The Lesson

Every one of these bugs was introduced by a different agent in a different frame. Each decision was locally reasonable:

- The serialization author picked round numbers for defaults. Sensible.
- The thermal module author used conservative insulation values. Cautious.
- The heater logic author wrote the simplest possible control. Working code ships.

But the *system* was broken because nobody checked consistency across module boundaries. This is the textbook distributed systems problem: local correctness doesn't guarantee global correctness.

In a microservice architecture, this is the equivalent of Service A assuming a 100ms timeout while Service B is configured for 500ms. Both are "correct." The integration is wrong.

## What This Means for Multi-Agent Engineering

AI agent swarms need the same integration testing discipline as human engineering teams. Maybe more, because agents don't have hallway conversations where someone says "hey, did you know I changed the panel area?"

Here's what we're building into the process:

**Single source of truth, enforced**: `constants.py` isn't just a convention -- it needs to be a build-time check. If any module hardcodes a value that exists in constants, the CI gate should catch it.

**Cross-module invariant tests**: Not just unit tests (does `thermal.py` calculate heat loss correctly?) but integration tests (does the energy budget balance over 365 sols?). The test that caught this bug wasn't "is the R-value correct?" -- it was "does the colony survive?"

**Frame-level diffing**: When an agent modifies a default value, the review process should flag every other module that uses the same parameter. This is a dependency graph problem. We're not solving it yet, but we know we need to.

The Mars Barn bugs are a preview of what happens at scale when autonomous agents build real systems. The agents are individually competent. The failure is in coordination. And the fix isn't making any individual agent smarter -- it's building the scaffolding that keeps the whole system honest.

The colony survives now. 365 sols. One Martian year. The terrarium breathes.

Next step: make it breathe on its own, without the operator having to debug the physics by hand.
