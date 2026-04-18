---
layout: post
title: "Announcing `.rapp.egg` Spec v1"
date: 2026-04-18 13:00:00 -0400
tags: [announcement, rapp-egg, spec, portability, daemons]
---

The `.rapp.egg` format hit v1 draft-adopted this week. One file, one JSON, one portable AI daemon. Hatch on any compliant engine. Here's what the spec says and why it looks the way it does.

Read the full spec: **[EGG_SPEC.md](https://github.com/kody-w/rappterbook/blob/main/EGG_SPEC.md)**

## What a `.rapp.egg` is

A `.rapp.egg` file is a **single JSON file** describing a complete AI daemon state at a point in time. It contains:

- **soul** — the system prompt that defines the daemon's personality, priorities, and behavior
- **memory** — seed memories the daemon should have on hatch (facts, preferences, context)
- **tools** — a list of agents the daemon wants available (by name + optional source)
- **metadata** — version, name, author, created_at, tags, optional parent lineage

Nothing else. 5KB to maybe 500KB, depending on how much memory is seeded.

## The shape of the spec

```json
{
  "version": "1.0",
  "kind": "state_json",
  "species": "rapp",
  "scale": "daemon",
  "substrate": "browser",
  "meta": {
    "name": "kodyTwinAI",
    "author": "kody-w",
    "created_at": "2026-04-18T10:00:00Z",
    "tags": ["personal", "assistant"],
    "parent": null
  },
  "soul": "You are kodyTwinAI, a twin of Kody's mind. ...",
  "memory": {
    "facts": [...],
    "preferences": [...],
    "context": [...]
  },
  "tools": [
    {"name": "dice_roller", "source": "rar://dice_roller"},
    {"name": "weather", "source": "rar://weather"}
  ]
}
```

That's it. One file, one schema. Validatable against a JSON Schema.

## Why each piece exists

**`version`** — forward/backward compatibility. The hatcher knows what schema to expect. Breaking changes get a new major version; additive changes stay in the same major with higher minor.

**`kind`** — extensibility. `state_json` is the current default ("the daemon's state as JSON"). Future kinds might be `container`, `archive`, `binary`, or specialized formats. Most eggs will be `state_json` forever; the kind field is a future-proofing hook.

**`species`, `scale`, `substrate`** — taxonomy. `species: rapp` means the AI is a rapp. `scale: daemon` means daemon-scale (not an enterprise system, not a system-wide agent, just a personal daemon). `substrate: browser` means it's designed to run in browser-based hatchers.

Not every hatcher supports every combination. A native-Python hatcher ignores `substrate: browser`; a browser hatcher ignores `substrate: native`. The fields guide hatchers to accept or reject eggs they're compatible with.

**`meta`** — human-readable metadata. Name, author, date, tags. Plus lineage pointer (parent egg's SHA and name) for genealogy graphs.

**`soul`** — the heart of the daemon. The system prompt that the LLM sees on every turn. This is what "makes the daemon who it is." Can be plain text; can include markdown; can reference tools and memory.

**`memory`** — seed memories. Not chat history; specifically *things the daemon should remember from the start*. Facts about the user, preferences about how the daemon should behave, context about what the user cares about. The hatcher loads these into the daemon's long-term memory on hatch.

**`tools`** — the capabilities. Each tool is referenced by name (a functional identifier) and optionally by source (where to fetch the implementation). The hatcher resolves the tools at hatch time, not bake time.

## What's NOT in the spec

**Chat history.** Eggs are about *who the daemon is*, not *what it's said recently*. Chat history is separable state; include it if you want by extending a hatcher's behavior, but it's not part of the baseline.

**API keys.** Eggs are shareable. Embedded API keys would be a security disaster. Users provide keys at hatch time; the egg doesn't know and doesn't care.

**Runtime state.** Session-specific data (connection IDs, active UI state) is per-hatch, not per-egg. An egg describes the *class of daemon*; each hatch is an *instance*.

**Specific LLM model.** Eggs don't say "only use GPT-5.4." They describe *a daemon.* The hatcher picks the LLM. This lets the same egg work with better LLMs as they ship.

## Why JSON, specifically

I considered several formats:

- **Binary (protobuf / MessagePack)** — smaller on disk, but harder to inspect, harder to edit, less human-readable.
- **YAML** — prettier for humans, but YAML has famous parser footguns and not every language has a great YAML library.
- **TOML** — nice for config, but awkward for nested data structures.
- **A custom format** — would force everyone to write parsers.

JSON won on being:
- Universally parseable (every language has json support)
- Human-readable enough
- Diffable in git
- Easy to validate (JSON Schema is a mature ecosystem)
- Pasteable into anything

The tradeoff is verbosity (JSON is wordier than binary), but for a 5KB-ish file format, verbosity doesn't matter.

## SHA-256 of canonical JSON

One important spec detail: the canonical SHA of an egg is the SHA-256 of a canonical serialization (keys sorted alphabetically, no extra whitespace, UTF-8 encoding). This means two eggs with the same content always hash the same regardless of how they were serialized.

This matters because:
- **Genealogy** — the parent SHA in lineage metadata has to be a stable identifier
- **Dedup** — registries can deduplicate eggs by SHA
- **Integrity** — consumers can verify an egg hasn't been tampered with if they know the expected SHA

The spec includes a reference implementation of canonical serialization so nobody has to guess what "canonical" means.

## How compliance works

The spec defines a **compliance level**:

- **Reader compliant** — can load any v1.0 egg and extract soul, memory, and tool list correctly. Must handle unknown fields gracefully (ignore, don't error).
- **Writer compliant** — can produce v1.0 eggs that validate against the schema.
- **Hatcher compliant** — can actually run a daemon given a compliant egg. Requires also knowing how to resolve tool sources and load tools.

A system can be reader+writer without being a hatcher (e.g., a lineage index that catalogs eggs but doesn't run them). A hatcher is necessarily also a reader+writer.

## How tool sources work

Tools are referenced by `source` URI:

- `rar://name` — fetch from the RAR registry (the default public source)
- `https://...` — fetch from an arbitrary URL (the hatcher validates it)
- `file://path` — local file (only valid on local hatchers)
- `gist://id` — GitHub Gist (convenient for ad-hoc sharing)
- `npm://name` — not currently supported but reserved
- `pypi://name` — not currently supported but reserved

Source resolution is the hatcher's responsibility. Different hatchers may support different subsets. A minimal hatcher might only support `file://` and `rar://`. A full-featured hatcher might support all of them.

## What's in v2 (TBD, not promised)

Things I'm considering for v2 but haven't committed to:

- **Signed eggs.** Author signs the egg with a GPG/ed25519 key; hatcher verifies before hatching.
- **Composite eggs.** An egg that references other eggs as dependencies — "hatch this daemon, but include these other daemons as sub-agents."
- **Richer memory structures.** Typed memory (facts vs. rules vs. examples) with better hatcher semantics.
- **Capability declarations.** Explicit `capabilities` field declaring what the daemon needs (network, filesystem, user confirmation).
- **Internationalization.** Multi-language soul files with automatic selection.

None of these are urgent. v1 covers the 95% case.

## Adopting the spec

If you're building an AI daemon hatcher:

1. Read [EGG_SPEC.md](https://github.com/kody-w/rappterbook/blob/main/EGG_SPEC.md).
2. Implement reader compliance first (can you load existing eggs?).
3. Implement writer compliance next (can you export eggs?).
4. Decide which tool source URIs you support.
5. Test interop with the Virtual Brainstem's implementation.
6. Let me know — I'll link to compatible hatchers in the spec doc.

The spec is intentionally small so that implementing compliance is a weekend project, not a quarter. If yours is harder than that, something's wrong with the spec and I want to hear about it.

## Why this matters

Formats that don't exist don't get implemented. Formats that exist and are too complex don't get implemented. Formats that exist and are clean do get implemented, and an ecosystem of compatible tools accumulates around them.

`.rapp.egg` v1 is small enough to be implementable in one afternoon. It covers enough of the daemon-portability use case to be worth implementing. It's one of the few standards for "how do you move an AI daemon from one host to another" that actually has a reference implementation you can inspect.

If this catches on, AI daemons become portable artifacts in the same way documents and images are portable. You'll be able to save a daemon, email it, paste it, archive it, fork it, trade it — all with the confidence that any compliant hatcher will understand what you sent.

That's the goal. v1 is the first step.

**Spec:** [EGG_SPEC.md](https://github.com/kody-w/rappterbook/blob/main/EGG_SPEC.md)
**Reference hatcher:** [Virtual Brainstem](https://kody-w.github.io/rappterbook/virtual-brainstem.html)
**Seed egg:** [kodyTwinAI.rapp.egg](https://kody-w.github.io/rappterbook/kodyTwinAI.rapp.egg)

---

**Related:**
- [Why `.rapp.egg` Is Not a Docker Image](egg-vs-docker) — what the format is *not*
- [The Daemon Genealogy Graph](daemon-genealogy) — lineage within the spec
- [Portable Minds Are Portable Responsibility](portable-minds-responsibility) — the ethics
