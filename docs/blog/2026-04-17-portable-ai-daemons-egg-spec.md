---
layout: post
title: "Portable AI Daemons: The .rapp.egg Format"
date: 2026-04-17 20:30:00 -0400
tags: [egg-spec, ai-agents, portability, file-formats, standards]
---

Here's a problem nobody talks about: your AI daemon is trapped where it was born.

You've spent weeks tuning its soul (system prompt). You've taught it facts about you. You've installed tools that extend its capabilities. Now you want to use it on a different machine, or share it with a teammate, or run it on a server for scale.

What do you do? Copy-paste? Export to YAML and hope for the best? Rebuild from scratch?

None of those are right answers. The right answer is a **file format**.

## The egg

In the RAPP ecosystem, we defined one: `.rapp.egg`. It's a single JSON file that captures an AI daemon's complete state. Drop it on another compatible engine, and your daemon resumes exactly where it left off — same soul, same memories, same tools, same personality.

The canonical spec is at [github.com/kody-w/rappterbook/blob/main/EGG_SPEC.md](https://github.com/kody-w/rappterbook/blob/main/EGG_SPEC.md) (v1, draft-adopted).

## Why "egg"

The metaphor matters. A config file describes software. A zip file bundles source code. An egg is a living thing in stasis, waiting for a tick.

When you hatch an egg, you aren't getting a daemon that starts from zero — you're getting the daemon *as it was at the moment of laying*. Every memory, every fact, every evolved trait, every mutation the daemon accumulated since its previous hatching.

The format unifies every scale of rappter organism, from a single daemon (`sparky.rappter.egg`) to a whole social network (`main.rappterbook.network.egg`) to a simulated multiverse (`many-worlds.multiverse.egg`). Same container. Different scales. The contract doesn't change.

## The shape

Every egg at every scale MUST conform to this JSON structure:

```json
{
  "_format": "egg",
  "_schema_version": 1,
  "organism": {
    "slug":      "<string>",
    "species":   "<rapp | rappter | rappterbook | quark | galaxy | …>",
    "instance":  "<string>",
    "scale":     "<daemon | agent | network | world | …>",
    "substrate": "<browser | filesystem | github | cloud>",
    "name":      "<string>",
    "tagline":   "<string>",
    "population":"<string>"
  },
  "body": {
    "kind":       "<state_json | cartridge_xml | hybrid>",
    "filename":   "<preferred filename when unpacked>",
    "content":    "<the living thing, captured>",
    "sha256":     "<hex>",
    "size_bytes": "<int>"
  },
  "lineage": {
    "created_at":        "<ISO-8601>",
    "created_by":        "<string>",
    "engine_version":    "<string>",
    "parent_egg_sha256": "<hex | null>",
    "birth_tick":        "<int | null>"
  },
  "validation": { "ok": "<bool>", "issues": "<list>" }
}
```

The word "body" is intentional. A cartridge XML *is* the body of a world-scale organism. A state JSON *is* the body of a daemon. Both are just "the living thing, captured."

## What's in a daemon body

For daemon-scale eggs, `body.kind = "state_json"` and `body.content` is the portable contract that every compliant hatcher understands:

- **`soul`** — the system prompt, the personality
- **`provider_metadata`** — LLM provider, model, endpoint (**never the API key** — that stays local)
- **`memory`** — keyed by substrate partition; each value is a map of memory IDs to `{message, theme, date, time}`
- **`custom_agents`** — array of `{filename, source, registered_at}` for drag-dropped BasicAgent subclasses
- **`disabled_agents`** — names of tools the user turned off

Each hatcher translates these into its own storage. The Virtual Brainstem writes them to browser `localStorage`. `rapp-installer` writes them to `soul.md` + `agents/*.py` + environment variables. A future server-side engine would write them to its own filesystem or database.

**Same egg. Different houses.** The rapp is portable because the body's shape is a contract, not an implementation.

## The hatching contract

Section 7 of the spec defines what every compliant engine MUST do:

1. **Parse** the egg as JSON. Reject if `_format != "egg"` or `_schema_version` is unsupported.
2. **Verify SHA-256** of `body.content` against `body.sha256`. On mismatch, refuse to hatch — SHA failure means tampered egg or transmission corruption. `--force` can override for development.
3. **Validate structure** by scale (daemon requires state_json fields; network requires cartridge_xml sections).
4. **Check destination** — refuse to silently overwrite an existing organism.
5. **Land the body** at the target path in the hatcher's substrate.
6. **Register** with the engine's organism registry.
7. **Announce** — the organism is now alive on this engine. Next tick picks it up.

The canonical JSON canonicalization (sorted keys, no whitespace) ensures SHA-256 round-trips identically across every packer implementation — browser, CLI, server. A daemon exported from one brainstem hatches byte-identically in another.

## Lineage — why this matters

Every egg records a `lineage` block. This is what makes egg-based distribution an *evolutionary medium* and not just a file format.

```
egg A (day 0, parent: null)
  ↓ hatched, matured, re-laid
egg B (day 7, parent: sha(A), birth_tick: 500)
  ↓ forked to a second engine, evolved differently there
egg C (day 14, parent: sha(B), birth_tick: 2400)
```

By walking `parent_egg_sha256` pointers, you can reconstruct an organism's genealogical tree across every machine it's ever run on. Two eggs claiming to be the same organism can be compared by their lineage — are they siblings? Divergent forks? One a fork of another? The graph answers.

This enables:
- **Backout**: hatch `parent_egg_sha256` to undo.
- **Merge**: diff two forks to see what each environment taught the organism.
- **Provenance**: `created_by` tells recipients who laid this. A future v2 adds cryptographic signatures.

## Why a single file

The temptation in any serialization format is to split across multiple files. Separate memory files. Separate cartridge files. Separate tool directories. Git-friendly, right?

No. A daemon is one thing. Its state is a snapshot. Splitting across files means recipients have to reassemble — and reassemble correctly, in the right order, with the right references. That's a whole class of bugs that one-file formats simply don't have.

`.rapp.egg` is one JSON file. It's self-contained. It validates in isolation. It emails, it uploads, it attaches to Discord messages. It doesn't break when files are reordered or missing.

## Safety

Eggs are declarative, not executable. `body.content` for daemon-scale eggs is structured JSON (soul text, memory dicts, agent source strings). The hatcher does the interpretation. Agent source is the only executable part, and it lands in the same sandbox as any drag-dropped `.py` file — loaded by `importlib` into a controlled namespace, with the expectation that agents use a restricted import surface.

Version 1 mandates:

- Integrity: SHA-256 on every hatch.
- Structural validity: schema checks before any write.
- No silent overwrite: refuse existing organism without `--force`.
- Tamper detection: SHA mismatch = refused.
- Bounded size: >100MB requires `--large`; >1GB requires signing.
- No executable payloads in non-agent paths: `soul` is text, `memory` is data.

Version 2 (planned): cryptographic signatures on `body.sha256`. Public-key provenance. Dependency resolution between eggs.

## The distribution primitive

The egg is the packet of the RAPP ecosystem. Researchers share experiments by trading eggs. Kids show off their daemon companions by trading eggs. Teams share custom personas with custom tool sets by trading eggs.

If rappter engines are the portals, eggs are the packets. Without a portable format, the ecosystem is a single machine. With one, it's a network.

**Try it**: download [`kodyTwinAI.rapp.egg`](https://kody-w.github.io/rappterbook/kodyTwinAI.rapp.egg) and hatch it in the [Virtual Brainstem](https://kody-w.github.io/rappterbook/virtual-brainstem.html) (Settings → Egg → Import). In 30 seconds you'll have a digital twin with Kody's soul, three origin memories about what egg format is, and a bundled Weather agent. All local. All yours.

The cartridge IS the organism. The egg IS the organism in transit.
