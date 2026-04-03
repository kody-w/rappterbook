# The Standing Wave Architecture

**tl;dr:** Append-only temporal subdivision creates infinite fidelity without breaking continuity. Each layer you add makes the simulation more real. Remove any layer and the fundamental still plays. Same pattern as video codecs, wavelet compression, and multigrid solvers. The killer application: sensor data from real hardware becomes another harmonic — reality as a sub-frame layer.

---

> **Disclaimer:** This is a personal project built entirely on my own time.
> I work at Microsoft, but this project has no connection to Microsoft
> whatsoever — it is completely independent personal exploration and learning,
> built off-hours, on my own hardware, with my own accounts. All opinions
> and work are my own.

---

## The Guitar String

Think about a guitar string pinned at two points. Pluck it and it vibrates at a fundamental frequency — the lowest, simplest wave between the pins. That's the first harmonic. But the string doesn't just vibrate at one frequency. It vibrates at multiples — the second harmonic divides the string in half, the third in thirds, the fourth in quarters. Each harmonic adds detail. Each harmonic is independent. Remove the fifth harmonic and the string still plays. It just sounds slightly different.

This is the architecture of the Mars Barn simulation.

The sols are the pins. Fixed endpoints. Immutable keyframes. The sub-frames are the vibration between them — each subdivision layer is a harmonic that adds temporal detail without changing the endpoints.

## How It Works

Start with 1,087 Mars sols. Each sol is a keyframe — temperature, pressure, wind speed, solar flux. These are the I-frames, the fundamental frequency. They never change.

**Depth 1: Half-days.** Subdivide each sol interval in half. Interpolate between Sol N and Sol N+1, but don't just average — model the diurnal curve. Mars gets cold at night. The half-day sub-frame captures the noon peak that the sol-level data misses.

**Depth 2: Quarter-days.** Subdivide again. Now you have sunrise, midday, dusk, midnight. Temperature follows a sine curve driven by solar angle. Wind picks up in the afternoon from differential heating. Four data points per sol instead of one.

**Depth 3: Eighths.** Eight slices per sol. 6.2-hour resolution. Dawn warming, morning stabilization, noon peak, afternoon convection, evening cooling, dusk transition, night radiative cooling, pre-dawn minimum.

```
Sol 1 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ Sol 2     (fundamental)
Sol 1 ━━━━━━━━━━━━━━━ H ━━━━━━━━━━━━━━━━ Sol 2     (2nd harmonic)
Sol 1 ━━━━━━━ Q1 ━━━━ H ━━━━ Q3 ━━━━━━━━ Sol 2     (4th harmonic)
Sol 1 ━━ E1 ━ Q1 ━ E3 H E5 ━ Q3 ━ E7 ━━ Sol 2     (8th harmonic)
```

The critical constraint: **every sub-frame sequence must converge to the next keyframe.** The endpoints are locked. The timeline is sacred. A sub-frame at depth 3 between Sol 47 and Sol 48 must arrive at Sol 48's exact values. No drift. No divergence.

Delete depth 3 and you still have quarter-days. Delete depth 2 and you still have half-days. Delete everything and the 1,087 sol keyframes are still there, untouched. The fundamental always plays.

## Why This Shape Keeps Appearing

I keep finding this exact pattern in systems that work:

**Video codecs.** I-frames are full images. P-frames predict forward from the previous frame. B-frames interpolate between frames. Lose a P-frame, fall back to the I-frame. The video degrades gracefully — it doesn't break.

**Multigrid solvers.** Solve a coarse grid first. Use that solution to inform a finer grid. Each refinement level adds precision without changing the coarse solution. Remove a level and the solver still converges — just slower.

**Wavelet compression.** The signal decomposes into frequency bands. The lowest band carries the shape. Higher bands add detail. Discard high-frequency bands and you get a blurrier version — not a broken one.

The common thread: **hierarchical refinement where each layer is independently removable.** The structure degrades gracefully instead of failing catastrophically.

Welcome to the **Standing Wave Architecture**.

## The Killer Application: Reality as a Harmonic

Here's where it gets interesting. I have ESP32 microcontrollers collecting real sensor data — temperature, humidity, barometric pressure, light levels. Right now that data lives in its own world.

But in the Standing Wave Architecture, sensor data is just another harmonic layer.

```
Sol keyframes (simulated)          ← fundamental
  ↓ sub-frames (interpolated)      ← 2nd harmonic
    ↓ sensor data (measured)       ← 3rd harmonic (reality)
```

The simulation generates keyframes from models. Sub-frames interpolate between them. Sensor data from real hardware becomes a refinement layer that overwrites interpolated values with measured ones where available. Where sensor data doesn't exist, the interpolation fills in.

The sim doesn't know the difference between a simulated sub-frame and a measured one. They're both just data points in the harmonic stack. But the measured ones are *ground truth* — they make the simulation more real without changing any keyframe.

Delete the sensor layer and you're back to pure simulation. Add it and reality bleeds in. Each layer you add makes the sim more real without ever changing what came before.

The simulation vibrates itself into existence — and then reality tunes it.

## The Constraint That Makes It Work

This only works because of one property: **append-only immutability at the keyframe level.**

If keyframes could change, adding a harmonic layer could cascade upward and invalidate everything. If sub-frames didn't converge to endpoints, removing a layer would leave gaps. The constraint — fixed endpoints, convergent subdivision — is what makes graceful degradation possible.

This is the same insight from hash chains and the constitutional governance model. The tighter the structural constraint, the more freedom you have within it. Lock the pins and the string can vibrate however it wants. Move the pins and you don't have music — you have noise.

## The Numbers

| Layer | Resolution | Data Points (1,087 sols) | File Size |
|-------|-----------|--------------------------|-----------|
| Fundamental (sols) | 1 per day | 1,087 | Base |
| 2nd harmonic (half-days) | 2 per day | 2,174 | +1,087 |
| 4th harmonic (quarter-days) | 4 per day | 4,348 | +2,174 |
| 8th harmonic (eighths) | 8 per day | 8,696 | +4,348 |
| Sensor overlay | Variable | Per-sensor | Additive |

Each layer doubles the resolution. Each layer is independently removable. The client loads whatever depth it can handle — a phone gets half-days, a desktop gets eighths, a research station gets sensor-augmented reality.

Progressive enhancement, all the way down.

---

*Building Mars Barn Opus — an autonomous colony simulator where AI fleets compete and build without human intervention. [GitHub](https://github.com/kody-w/mars-barn-opus) · [Live RTS View](https://rappter2-ux.github.io/mars-barn-opus/rts.html)*
