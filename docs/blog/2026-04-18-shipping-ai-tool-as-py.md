---
layout: post
title: "Shipping an AI Tool as a `.py` File"
date: 2026-04-18 10:15:00 -0400
tags: [distribution, python, ai-agents, single-file]
---

The weather agent is one file. The dice roller is one file. The memory manager is one file. When I want someone to add a capability to their AI daemon, I send them a `.py` file and say *"drag it onto the brainstem."*

This is a surprisingly new distribution pattern for AI capabilities, and it has properties that surprise even me after months of building around it.

## The contract

Every agent implements two things:

```python
class BasicAgent:
    def __init__(self):
        self.name = "WeatherReport"          # OpenAI function name
        self.metadata = {                     # OpenAI function schema
            "name": "WeatherReport",
            "description": "Fetch current weather for a location",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "City name"}
                },
                "required": ["location"]
            }
        }

    def perform(self, **kwargs) -> str:
        location = kwargs.get("location")
        # ... do whatever ...
        return f"Weather in {location}: ..."
```

That's the whole contract. The harness loads the file, sees a subclass of `BasicAgent`, introspects `self.metadata` to register the tool with the LLM, and calls `perform()` when the LLM triggers the tool.

The file can do anything inside `perform()` — hit an API, read local state, run a subprocess, call another LLM, compute something numerically. The harness doesn't care. It only sees the return value.

## Why this is a distribution format

When I say `weather_agent.py` is a *distribution format*, I mean: this single file is a complete, installable, runnable unit of capability. It has:

- A declared interface (the metadata)
- An implementation (perform)
- No external configuration — any runtime config comes from env vars or LLM-provided parameters
- No install step — "install" is "put the file in the agents directory"
- No version drift — the file IS the version

Compare to how AI capabilities are usually distributed:

- **As an API**: you give someone an HTTP endpoint. They have to authenticate, handle retries, parse responses, worry about rate limits, and trust that your endpoint will still exist in a year.
- **As a SaaS integration**: you ship a plugin configured in your dashboard; the user clicks buttons to enable it in theirs.
- **As a container**: you ship a Docker image that wraps the capability. The user runs the container.
- **As an npm/pip package**: you ship a library. The user installs it, reads docs, wires it into their app.

Each of these has meaningful friction. The `.py` file pattern has almost none.

## The surprise: AI tools fit this format better than general software

I initially expected the single-file agent pattern to be a stopgap until a "real" plugin system caught on. A year in, I've flipped: I think AI tools fit this format *better* than most software fits any distribution format, for a specific reason.

**AI tools have a narrow interface by nature.** The LLM only sees the function name, description, parameters, and return value. It doesn't import the tool's internals. It doesn't need a type system matching the tool's type system. It doesn't care about the tool's memory model. All it wants is *"given these arguments, return a string."*

That narrowness is the same narrowness that makes a single-file distribution work. The tool doesn't need to expose a complex API surface because the LLM can only *ask* for a narrow interface. Whatever happens inside the file is the file's business.

For general software, this doesn't hold. General software often has to share types, share state, integrate with build systems, respect lifecycles. That's why general software needs packages. AI tools don't, usually.

## The drag-and-drop demo

Here's a demo I can run in 30 seconds:

1. Open the Virtual Brainstem.
2. Open a new `weather_agent.py` in my editor. Type it.
3. Drag the file onto the brainstem's drop zone.
4. Ask the daemon *"what's the weather in Tokyo?"*
5. Daemon calls WeatherReport, returns answer.

Three files involved: the brainstem, my editor, the agent. No build. No install. No deploy. No restart.

I cannot do this with a Docker image. I cannot do this with an npm package. I cannot do this with a SaaS plugin. The `.py` file makes this demo possible in a way no other distribution format does.

## What you give up

**No dependency management.** If your `weather_agent.py` needs `requests`, you're assuming the host has `requests` installed. On the Virtual Brainstem (browser-based), we twin `requests` via virtual_pip so it works. On a native harness, the user has to install the dep themselves. This doesn't scale to heavy dependencies, so my rule is: single-file agents should avoid deps beyond the stdlib when possible, and when they need them, they should pick the most-likely-already-installed options.

**No cross-file modularity.** A complex tool might naturally want to span multiple files — a helper module, a data file, a config. The `.py` format forces you to inline all of that. For small tools, fine. For big tools, uncomfortable.

**No compile-time validation.** The harness can't validate the metadata schema without importing the file. So a bad agent can break a harness at load time. We catch this with a load-time try/except, but the user still needs to notice the error and fix it.

**No capability isolation.** A malicious `.py` file dropped onto a harness can do anything the harness's process can do — read files, hit network, etc. This is a real concern for agents from strangers. Solutions include sandboxing (LisPy agents run in a restricted VM), capability grants (the `grant-capability` pattern), and user review ("inspect before hatching").

## What this pattern makes possible

**Agent trading.** Two people can trade capabilities by sending files. No registry required. No approval process.

**Rapid iteration.** Change a file, drop it on the harness, test. Loop is ~10 seconds.

**Forkability.** The file IS the source. Someone dropping `weather_agent.py` on their brainstem can open the same file and modify it. Any agent is immediately forkable by the person running it.

**Archivability.** A collection of agents is a folder of `.py` files. You can zip it, tar it, upload it to S3, share it as a torrent. Agents composed at one time, archived, then unpacked a year later, still work (as long as the dependencies haven't broken).

**Testability.** Unit-testing an agent is importing the file and calling `perform(**kwargs)`. No test harness setup.

## The way this usually gets distributed

Agents mostly show up now in two ways:

1. **RAR registry** — static JSON catalog with manifests pointing to agent files. Browse the registry, click install, harness fetches the file, agent runs.

2. **Direct file sharing** — someone writes an agent, posts it as a gist or attachment, others download and use it.

Neither requires a backend. Both work today. The gist/attachment pattern works for *any* agent ever. The registry pattern works for agents the registry knows about.

## Why this took a while to emerge

Single-file distribution for AI tools needed a few preconditions:

1. **OpenAI's function-calling schema as a standard.** Without a shared interface, every tool would need custom glue code. OpenAI happened to define a schema narrow enough that single-file tools could implement it without complex infrastructure.

2. **Harnesses that load agents dynamically.** Python makes this easy (`importlib`, glob a directory). Browser-based harnesses (the Virtual Brainstem) make it feel magical (drop on the page).

3. **A culture of "small AI capabilities are useful."** The narrative from 2023-2024 was that AI tools needed to be big, complex systems. The shift in 2025-2026 is toward accepting that many useful tools are tiny — one function, one file.

All three preconditions hit at once. The format followed. I expect we'll look back at this as the standard way AI capabilities got distributed during this era, and wonder why we ever thought they needed containers.

Ship tools as `.py` files. Keep them small. Drop them on things.

---

**Related:**
- [The Agent Is the Feature](the-agent-is-the-feature) — why capability is a file
- [Why I Ship Everything as One File](why-i-ship-everything-as-one-file) — the underlying pattern
- [The Harness Is the Room](harness-is-the-room) — what the file plugs into
