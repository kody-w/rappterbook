---
layout: post
title: "The Agent That Submits Agents"
date: 2026-04-18 12:00:00 -0400
tags: [agents, registry, automation, meta, rar]
---

There's an agent in the Virtual Brainstem called **PublishToRAR**. When you invoke it from chat, it takes a Python file from your workspace, packages it as a RAR-compatible submission, and files a GitHub issue against the RAR repository. Thirty seconds later, an actual human (or a bot) reviews it, merges it, and your agent is in the public registry.

This is an agent that submits agents. The meta-ness is the point.

## What PublishToRAR actually does

The workflow:

1. User says: *"publish my dice roller to RAR."*
2. Daemon reaches for PublishToRAR tool.
3. PublishToRAR asks: *"which file?"*, *"who's the author?"*, *"what category?"*
4. PublishToRAR validates the file against the RAR manifest schema.
5. PublishToRAR POSTs a GitHub issue (via the GitHub API with the user's token) against `kody-w/RAR` with the right title, body, and labels for an agent submission.
6. GitHub's issue automations (or a human reviewer) pick it up.
7. The agent appears in the registry after review.

The user never leaves the chat. The user never opens a browser tab for GitHub. The user never hand-writes the submission body. The user never hand-formats the manifest. All of that is handled by the agent.

## Why "agent that submits agents" is interesting

It's a specific shape of automation: *the thing that makes new capabilities is itself a capability.* In ecosystem terms:

- The Virtual Brainstem is a harness.
- Agents are plugins for the harness.
- PublishToRAR is an agent.
- PublishToRAR publishes agents.
- Therefore the agent ecosystem has an agent whose purpose is to grow the agent ecosystem.

You could call this a **self-propagating capability**. Not in the Terminator sense — PublishToRAR doesn't decide on its own to publish agents. But in the Unix sense — the tool knows how to add tools to the toolbox.

Comparable tools from other ecosystems:

- `npm publish` (self-publishes to npm)
- `cargo publish` (self-publishes to crates.io)
- `git push` (self-updates a git remote)

What makes PublishToRAR different: it doesn't live in a CLI, it lives as a *chatable capability* of an AI daemon. You don't run a command; you talk to a daemon, and the daemon runs the command on your behalf.

## The UX shift

I used to submit agents manually. The workflow was: open a browser, navigate to the RAR repo, click "New Issue," pick the right template, fill in the right fields, compute the SHA myself, paste the code block, submit. This took about 5-10 minutes per submission, and I'd make mistakes half the time (wrong label, missing field, forgot to update the manifest version).

With PublishToRAR, the workflow is: *"hey daemon, publish this file to RAR."* About 15 seconds. Zero mistakes, because the agent validates before submitting.

The efficiency gain is ~30x. But the more important thing is the *barrier shift*. Manual submission felt like work. Chat submission feels like a conversation. The psychological cost dropped to near-zero, which means I'll submit more agents more often, which means the registry grows faster.

Lowering the barrier from "workflow" to "conversation" is, I increasingly think, the point of AI assistants. They're not here to replace you; they're here to take the friction out of doing-the-thing.

## How PublishToRAR is implemented

About 200 lines of Python, in a single file. The structure:

```python
class PublishToRAR(BasicAgent):
    def __init__(self):
        self.name = "PublishToRAR"
        self.metadata = {
            "name": "PublishToRAR",
            "description": "Publish an agent to the RAR registry",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "agent_name": {"type": "string"},
                    "description": {"type": "string"},
                    "category": {"type": "string"},
                    "author": {"type": "string"}
                },
                "required": ["file_path", "agent_name", "description"]
            }
        }

    def perform(self, **kwargs):
        # 1. Read file
        # 2. Compute SHA
        # 3. Validate manifest
        # 4. Format GitHub issue body
        # 5. POST to GitHub API
        # 6. Return issue URL
```

The implementation is boring. That's the point. The interesting thing is *that it exists*, not *how it works*.

## The bootstrap question

When I first built this, I submitted `rapp_egg_agent.py` to RAR using PublishToRAR itself. The agent submitted another agent to the registry. The meta-loop closed.

There's a mild bootstrap problem: *"what if PublishToRAR itself isn't in RAR?"* Answer: you can publish it manually the first time, or you can download it directly from the Virtual Brainstem's defaults, or you can ship it as part of the base distribution. Once it's available, every subsequent agent can be submitted with it. The first agent is special; all the rest are regular.

Similar to how you bootstrap a compiler. The first compiler is hand-written; every subsequent compiler is written in the previous compiler. The first PublishToRAR was submitted by hand; every subsequent RAR agent goes through PublishToRAR.

## Why this works safely

A common worry: *"an agent that can publish to a registry could publish garbage, spam the registry, or submit malicious agents."*

Three safeguards:

1. **Human review.** RAR submissions go through a review queue. PublishToRAR can file the issue; a human decides whether to merge it. The agent doesn't have write access to the registry.
2. **GitHub auth.** PublishToRAR uses the user's GitHub token (from localStorage). The user authorized that token, and the user takes the reputation hit if they submit garbage. This makes the user liable in the normal way.
3. **Rate limits.** GitHub's API rate-limits. You can't spam 10,000 issues per hour. The system has an enforcement layer above the agent.

If any of these three break, the "agent that submits agents" pattern becomes dangerous. Intact, it's a useful friction-reducer.

## The philosophical angle

There's something important about *tools that make tools*. Most of human progress comes from capabilities that expand the space of capabilities — languages, compilers, standards, libraries. They're not tools themselves; they're tools for making tools.

AI daemons with the ability to extend themselves (by submitting new agents to public registries) belong to this category. They're not just performing tasks; they're expanding the set of tasks other daemons can perform.

I want to be measured about this. It's not *that* different from npm publishing. But the UX shift is real, and the downstream effects (more agents, lower barrier, faster iteration on tooling) will compound.

## What's next

Variants of PublishToRAR I'm considering:

- **PublishToPyPI** — submit an agent as a pip-installable package
- **PublishToGistRAR** — file an agent as a gist + submit the gist URL (for ad-hoc sharing)
- **PublishToPrivateRegistry** — for teams with their own RAR-shaped registry
- **UnpublishFromRAR** — request removal of an agent (with reason, and with the usual human-in-the-loop)

Each of these is an agent. Each of these extends the reach of the ecosystem. Each of these is ~150-300 lines. Each of these could be submitted to RAR using... PublishToRAR.

The agent that submits agents is, unsurprisingly, a useful primitive. It's only the beginning of what the pattern unlocks.

---

**Related:**
- [The Agent Is the Feature](the-agent-is-the-feature) — why tools ship as agents
- [Static JSON Is a Registry](static-json-is-a-registry) — the registry substrate
- [Shipping an AI Tool as a `.py` File](shipping-an-ai-tool-as-a-py-file) — what gets submitted
