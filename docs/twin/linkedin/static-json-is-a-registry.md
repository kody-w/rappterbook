---
created: 2026-04-18
platform: linkedin
status: draft
source: static-json-is-a-registry
tags: [engineering, architecture, github, devops, productivity]
cross_post: [x, devto]
register: linkedin-post
---

# Stop Building Backends for Read-Heavy Catalogs

If your catalog has a reads-to-writes ratio over 100:1, a flat JSON file in a git repo — served as a static asset — will out-perform the service you were about to build.

This sounds like a provocation. It's a observation from six months of running a live registry (RAR — 150+ AI agents, thousands of reads per day) on exactly this pattern. Zero servers. Zero database. Zero downtime. $0/month.

**The pattern:**

Your catalog lives in a git repository. Entries are either rows in a JSON file or individual files in a directory. A GitHub Actions workflow rebuilds the catalog JSON on every merge. GitHub Pages serves it as a static file. Consumers fetch the JSON directly — no API, no auth, no rate limits beyond GitHub's generous defaults.

**The underlying reasons this works:**

• Hosting is free at practical scale (GitHub Pages, Cloudflare Pages, S3)
• You inherit the platform's uptime (better than most self-hosted databases)
• Operational complexity collapses to near-zero — no DB to back up, no auth to maintain, no admin UI to build
• Mirroring is `git clone` — anyone can run a redundant copy, including air-gapped
• Audit trail is free — every change is a git commit, every submission is a PR or issue
• Private forks work for private variants

**What you give up (honest tradeoffs):**

• No real-time stats (you get per-build-frequency counts, not live)
• No built-in full-text search (but <5MB JSON grep's fast client-side)
• No cross-catalog SQL joins (do them in the client that consumes both)
• Write throughput is human-paced — human reviewers merge submissions

**Where the pattern fits:**

Agent registries, design token catalogs, dataset indexes, recipe databases, component libraries, API endpoint catalogs, org charts, public wiki content, reference documentation, price lists, FAQ databases.

**Where it doesn't:**

Active social networks, real-time multiplayer games, high-throughput transactional systems, any workload with balanced reads and writes.

**The meta-point:**

Most "registries" built in the last fifteen years are services because 2010 didn't have free static hosting at scale. That constraint is gone. The default in 2026 should flip — services for transactional workloads, static JSON for catalogs.

The tooling is mature. The pattern is boring. Boring is underrated in infrastructure.

Full writeup with template, concrete examples, and the history of why this wasn't viable until ~2018:
kody-w.github.io/rappterbook/blog/static-json-is-a-registry

If you're maintaining a read-heavy catalog as a service right now, I'd love to hear: could it be flat JSON + git? What would you lose? What would you gain?

#SoftwareArchitecture #DevOps #GitHub #StaticSites #Engineering
