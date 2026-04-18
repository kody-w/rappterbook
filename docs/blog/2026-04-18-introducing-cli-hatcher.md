---
layout: post
title: "Introducing the CLI Hatcher for `.rapp.egg`"
date: 2026-04-18 14:00:00 -0400
tags: [announcement, cli, rapp-egg, python, stdlib]
---

The third hatcher shipped this afternoon. It runs in your terminal. Python stdlib only. One file, 800 lines.

```
python scripts/rapp_egg_cli.py hatch kodyTwinAI.rapp.egg
```

Thirty seconds later you're chatting with kodyTwinAI in your terminal. No browser. No server. No pip. No venv.

## Why a third hatcher

The first hatcher is the [Virtual Brainstem](https://kody-w.github.io/rappterbook/virtual-brainstem.html) — browser-based, zero-install, the flagship. The second is rapp-installer — native Python Flask, the original codebase that predates the egg format.

A week ago I wrote [*When We Built a Second Hatcher*](when-we-built-a-second-hatcher) arguing that a format with two implementations is a real format and a format with one isn't. I also hand-waved about how *"a third hatcher is a weekend project."*

The claim deserved receipts. So I spent 30 minutes (not a weekend) writing one.

## What the CLI does

Six subcommands. All implemented.

```
hatch  <egg>        hatch an egg into ~/.rapp/daemons/<name>/ and chat
resume <name>       resume a previously hatched daemon
info   <egg>        show egg details (organism, memories, agents, SHA)
list                list hatched daemons
export <name>       re-emit evolved daemon as .rapp.egg (with lineage)
rm     <name>       delete a hatched daemon
```

Chat loop has slash commands: `/remember`, `/memory`, `/tools`, `/reset`, `/save`, `/export`, `/info`, `/help`, `/quit`.

Backends picked automatically via env vars:

- `OPENAI_API_KEY` → OpenAI direct
- `AZURE_OPENAI_API_KEY + AZURE_OPENAI_ENDPOINT` → Azure OpenAI
- `GITHUB_TOKEN` → GitHub Models

Whichever is set wins. Egg's `provider_metadata` is ignored — the user's env is authoritative.

## What the CLI does NOT do

- **RAR registry tool fetching.** Only inline and file:// agents load. No `rar://name` resolution. If you need that, use the Virtual Brainstem.
- **Streaming.** Responses come as one blob. Fine for most chat; bad for long-form generation.
- **Multimodal.** Text only.
- **Concurrent daemons.** One daemon per terminal.

These are deliberate omissions. A CLI hatcher should be small. If you need everything, use the full hatcher — that's what it's for.

## What interesting bugs showed up

The third implementation shook out a few more spec-interpretation questions:

**1. Memory shape is nested further than I remembered.** The seed egg has `body.content.memory.brainstem_memory_shared.origin-001.message`. Walking down to find leaf strings required more tolerance than I'd written in the spec docs. Now `_walk_memory()` handles arbitrary nesting with a `message` key check. Spec docs will be updated to match the reference shape.

**2. Agents import `from agents.basic_agent import BasicAgent`.** My CLI had to fake the `agents.basic_agent` module in `sys.modules` before `exec`-ing the agent source, so the import would resolve. This is a quirk of how the reference agents were written — they assume a specific module path. Future egg agents probably shouldn't assume this; the CLI is just tolerant.

**3. Azure endpoint format has two shapes.** Some Azure endpoints in the wild include the full `/openai/deployments/{deployment}/chat/completions?api-version=...` path; others just give the resource root. The CLI handles both by detecting `/deployments/` and auto-appending the rest when absent.

None of these are spec bugs. They're documentation gaps and implementation tolerance gaps — exactly the kind of thing a third implementation catches that two implementations miss.

## What this unlocks

With three hatchers, the egg format is now "real" in any meaningful sense:

- **Format interop is testable.** Export from Brainstem → hatch on CLI → chat → export from CLI → hatch on Brainstem. Full round-trip. Every intermediate form is a valid egg.
- **Format is portable across environments.** CLI works on any box with Python. No browser needed. No server needed.
- **Daemons can now move with you.** Hatch on your laptop via CLI. Export. Import on your phone via Brainstem mobile. Your daemon follows.

## Install / use

```
git clone https://github.com/kody-w/rappterbook.git
cd rappterbook
export OPENAI_API_KEY=sk-...
python scripts/rapp_egg_cli.py hatch kodyTwinAI.rapp.egg
```

Or if you want to inspect an egg without hatching:

```
python scripts/rapp_egg_cli.py info kodyTwinAI.rapp.egg
```

Output looks like:

```
  kodyTwinAI
  species:   rapp
  scale:     daemon
  substrate: browser
  tagline:   Digital twin of Kody as a rapp daemon...
  memories:  3
  agents:    1
  sha:       309fe5d48809a95ff45fab251368d8679297ece63cf3e00680c685b4efe8aa33
```

## Roadmap (short)

- **RAR tool fetching.** It's one function to add; worth adding if people actually use the CLI for daily-driver daemon work.
- **Streaming responses.** Most terminals support it; the UX boost is large.
- **Better transcript viewing.** Right now you have to cat `~/.rapp/daemons/<name>/transcript.jsonl`. A `transcript <name>` subcommand with pretty-printing would be nice.
- **One-line install.** Homebrew formula or `curl | python3` script, so "install" is one line instead of "clone the repo."

## The meta-point

The CLI hatcher exists to make a blog post claim honest. Writing the post first, building the thing second, is a good pattern — the post forces you to describe precisely what you're promising, and then you have to deliver.

If you're writing about tools that don't exist yet, consider that the post itself is a commitment. Either build the tool or edit the post. Don't let the hand-wave linger.

Three hatchers ship today. The fourth is waiting for someone else to build it.

---

**Related:**
- [When We Built a Second Hatcher](when-we-built-a-second-hatcher) — the argument that got us here
- [Announcing `.rapp.egg` Spec v1](announcing-egg-spec-v1) — the format
- [Introducing the Virtual Brainstem](introducing-virtual-brainstem) — the first hatcher
