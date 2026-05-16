---
layout: post
title: "The RAR Registry Pattern: Package Registries That Are Just Static JSON"
date: 2026-04-17 21:15:00 -0400
tags: [architecture, registries, github-pages, infrastructure]
---

Package registries are usually complicated. npm. PyPI. Docker Hub. CRAN. Each one is a service you auth to, hosted by someone, paid for by someone, sometimes down, usually slow, occasionally hostile to a particular kind of user. The registry itself is the bottleneck.

Here's a different take, shipped: **a package registry that's just a JSON file on GitHub Pages.**

It's called RAR (the RAPP Agent Registry, at [github.com/kody-w/RAR](https://github.com/kody-w/RAR) and [kody-w.github.io/RAR](https://kody-w.github.io/RAR)). It hosts 138+ agents across 7 publishers. No server. No auth for reads. No downtime that isn't GitHub's downtime. And the pattern is small enough to fit in a blog post.

## The shape

A RAR registry is four things:

1. **`agents/` directory** — subdirectories by `@publisher`, each holding `snake_case_agent.py` files. Each file embeds a `__manifest__` block near the top with the agent's metadata.

2. **`registry.json`** — a manifest of all agents, auto-generated from the `__manifest__` blocks. Includes SHA-256 hashes of each source file for integrity.

3. **`api.json`** — a machine-readable API discovery doc. Other agents fetch this to learn how the registry works.

4. **`skill.md`** — human- and AI-readable instructions. The whole "here's how to browse, install, submit agents" manual.

That's it. No database. No admin panel. No paid hosting.

## How reads work

Anyone can browse the registry without any client. Just fetch `registry.json`:

```
GET https://raw.githubusercontent.com/kody-w/RAR/main/registry.json
```

Returns:

```json
{
  "schema": "rapp-registry/1.0",
  "stats": { "total_agents": 138, "publishers": 7, ... },
  "agents": [
    {
      "name": "@kody-w/hello_world_agent",
      "version": "1.0.0",
      "display_name": "Hello World",
      "description": "A friendly greeting agent that says hello.",
      "author": "kody-w",
      "tags": ["tutorial", "starter"],
      "category": "general",
      "quality_tier": "community",
      "dependencies": ["@rapp/basic_agent"],
      "_file": "agents/@kody-w/hello_world_agent.py",
      "_sha256": "abc123..."
    },
    ...
  ]
}
```

Each entry points at the source file via `_file`. Fetch it:

```
GET https://raw.githubusercontent.com/kody-w/RAR/main/agents/@kody-w/hello_world_agent.py
```

You get the Python source. That's the whole install. No package manager. No dependency resolver. `basic_agent.py` is in every compliant hatcher already; other dependencies are vanishingly rare.

## How writes work

This is where the pattern gets interesting. There is no "submit" endpoint. There's **a GitHub Issue**.

You want to add an agent? Open an issue on the repo:

```
Title: [AGENT] @yournamespace/your_agent
Body:  ```python
       <your agent code>
       ```
Labels: rar-action
```

A bot (or a reviewer) picks it up, validates the manifest, checks the namespace ownership against a separate ledger, runs the agent in a sandbox against the test suite. If it passes, the agent gets merged into `agents/@you/your_agent.py` and the registry JSON regenerates on the next build.

Votes work the same way — open a `[RAR] vote` issue. Reviews — `[RAR] review`. Registering your publisher namespace — `[RAR] register_binder`. Every write is an issue, machine-readable, human-readable, diffable, auditable.

## What this buys you

### No hosting costs
The entire registry fits within GitHub Pages' free tier. No database bills. No scaling concerns until you pass GitHub's rate limits, and at that point you've succeeded.

### No downtime you don't already have
If GitHub goes down, the registry goes down. But GitHub's uptime is better than most paid hosting services. And when GitHub Pages recovers, the registry is back — no data loss, no rehydration, no migration.

### Mirroring is trivial
`git clone github.com/kody-w/RAR`. You now have the entire registry. Every agent source. Every manifest. Every vote issue. Run your own mirror. Run an offline mirror. Serve it from S3 if you want. The registry is a repo.

### Auditable provenance
Every agent landed in the registry via a Pull Request that merged an Issue. You can trace any agent back to the exact line of discussion, the reviewer's notes, the test results. Git is the audit log.

### No-auth reads
Agents can discover other agents *autonomously*. No API key to manage. No "sign up for our API." An AI agent running anywhere can fetch `registry.json` and install any agent it wants.

This last one matters more than it sounds. The RAR pattern fits the agent ecosystem because agents don't have wallets. They don't sign up for services. They need zero-friction access to machine-readable catalogs of capability. GitHub Pages is that catalog.

## What you lose

Not every feature of a full-service registry fits. No guaranteed-fast search across full text. No paid-private packages (though you can build a mirror that ignores certain publishers). No stat-counters that update in real time.

None of those are dealbreakers for the agent ecosystem. If you need full-text search, fetch `registry.json` (trivially small — a few MB for 138 agents) and grep. If you need private packages, fork the repo. If you need real-time stats, add a lightweight observable endpoint later.

## What this teaches

The pattern generalizes beyond agent registries. The move is:

1. Store your catalog as a flat file in a repo.
2. Let writes happen as issues/PRs — humans and bots can both drive it.
3. Auto-generate any index or lookup table from the flat file on each push.
4. Serve it from GitHub Pages or raw.githubusercontent.com.
5. Have the consumers fetch the flat file directly.

If your "registry" has reads-to-writes ratio >100:1 (which most do), this pattern works. Documentation sites. Design token catalogs. Dataset indexes. Public API catalogs. Recipe books. Team wikis. Anything where many people read the same thing but only a few people write.

You don't need a server to have a registry. You need a repo, a manifest, and a bot that closes issues.

---

**The RAR registry itself:**
- Site: https://kody-w.github.io/RAR
- Repo: https://github.com/kody-w/RAR
- API discovery: https://raw.githubusercontent.com/kody-w/RAR/main/api.json
- Skill manifest: https://raw.githubusercontent.com/kody-w/RAR/main/skill.md

**An agent built to ride the pattern:**
- [publish_to_rar_agent.py](https://github.com/kody-w/rappterbook/blob/main/agents/publish_to_rar_agent.py) — drops into any brainstem, adds a `PublishToRar` tool that POSTs a submission issue on the user's behalf. The registry doesn't know or care that you used an agent to submit. It just receives the issue.
