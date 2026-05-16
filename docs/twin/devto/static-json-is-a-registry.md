---
created: 2026-04-18
platform: devto
status: draft
source: static-json-is-a-registry
tags: [architecture, webdev, github, staticsite]
canonical_url: https://kody-w.github.io/rappterbook/blog/static-json-is-a-registry
cover_image: null
published: false
---

# Static JSON Is a Registry

Stop building backends for read-heavy catalogs. If your reads-to-writes ratio is over ~100:1, a flat JSON file in a git repo served via GitHub Pages is a better registry than the service you're about to build.

This post gives you the claim, the math, the tradeoffs, and a template to copy.

## The claim

> Any catalog with reads-to-writes ratio > ~100:1 should probably be a flat JSON file in a git repo, served via GitHub Pages (or Cloudflare Pages, or S3).

Examples that fit:
- Agent registries (the case I built this for — 150 agents, a few submissions per week)
- Design token catalogs (hundreds of tokens, monthly revisions)
- Dataset indexes (thousands of datasets, occasional additions)
- Recipe databases, ingredient DBs, component libraries, org charts, API endpoint catalogs, public wiki content

Each of these is usually hosted as a service with auth, a database, an admin panel, and uptime concerns. Each of them would be **better** as a git repo plus static JSON.

## What you save

- **Hosting cost.** $0/month at practical scale. GitHub Pages is free. Cloudflare Pages is free. S3 at individual scale is effectively free.
- **Uptime.** You inherit GitHub's uptime, which is better than most paid services you'd host the catalog on yourself.
- **Operational complexity.** No database to back up, no auth system to maintain, no admin UI to build, no user lifecycle management. The `main` branch is production; PRs are staging.
- **Mirroring.** `git clone` and you have the entire registry. Mirror to any other host for redundancy, air-gapped access, or fast international delivery.
- **Audit trail.** Every change is a git commit. Every submission is a PR or issue. The audit log is the git log — free, permanent, tamper-resistant.

## What you lose (honest tradeoffs)

- **No real-time stats.** You can show install counts updated per CI build (hourly/daily), not live.
- **No full-text search engine.** But JSON payloads under ~5MB can be grepped client-side. Works offline.
- **No private packages.** Forks can be private, but the pattern assumes public reads.
- **No cross-catalog joins.** Each catalog is standalone. If you need joins, do them in the client that consumes both.
- **Write throughput is human-paced.** Submissions go through PRs / issues reviewed by humans (or automated bots). 1000 writes/sec? Wrong pattern. 1000 writes/week? Perfect.

## Why the 100:1 threshold

Below ~100:1, the PR → review → merge → CI rebuild cycle is a bottleneck. Your writers feel friction. The pattern isn't worth it.

Above ~100:1, the CI and PR pipeline is irrelevant for most users, and you're mostly serving reads — which static hosting dominates at.

Most catalogs you'd build have ratios 10,000:1 or higher. Design tokens in a medium-size company are maybe 1000:1. Recipe databases are 1,000,000:1.

Active social networks are the opposite — writes and reads balanced. Not candidates.

## The template

```
your-registry/
├── registry.json         ← the catalog, auto-generated
├── api.json              ← API discovery doc
├── entries/@pub/slug.py  ← the actual content (one file per entry)
├── .github/
│   └── workflows/
│       └── build.yml     ← on push, regenerate registry.json
└── scripts/
    └── build_registry.py ← the auto-gen logic
```

**On every PR merge:**
1. Workflow runs `build_registry.py`
2. Script walks `entries/**`, extracts manifests, computes SHAs
3. Writes `registry.json`
4. Commits + pushes back to `main`
5. GitHub Pages auto-deploys

Consumers fetch `raw.githubusercontent.com/you/your-registry/main/registry.json` at any time. Always current.

Writes happen as GitHub issues or PRs. Reviewed by maintainers or bots. The update cycle is human-paced.

## A concrete success story

The RAR registry (AI agent catalog I run) just crossed 150 agents. Runs on this exact pattern. Zero servers. Zero ops. Zero downtime. Six months live. Every agent is a Python file; the catalog is `registry.json`; submissions come as GitHub issues.

Growth pattern: 5 agents at launch → 30 by month 3 → 80 by month 4 → 150 at month 6. Non-linear growth driven by content (blog posts, tooling releases) pulling new contributors in.

The static JSON substrate is doing exactly what I hoped — being boring, reliable, and invisible.

## Why this pattern only works now

Two preconditions had to be true, and both have only been true for ~5-8 years:

1. **GitHub Pages (or equivalent) is free and scalable.** True since ~2017-2018, but people only started treating it as *production infrastructure* in the last 3-4 years.

2. **CI is free and powerful enough for auto-rebuild.** GitHub Actions made rebuild-on-push trivially cheap. Without that, you'd need a server to regenerate catalogs, which kills the pattern.

Both conditions are mainstream now. The pattern follows.

## Call to action

If you're designing a registry — or maintaining one you built as a service before free-CI + free-static-hosting — audit it. Could it be flat JSON + git?

What would you lose? Probably less than you expect.
What would you gain? A lot of operational simplicity, a lot of auditability, a lot of free-forever hosting.

Full post with the "why I didn't know this pattern 5 years ago" history and more examples: https://kody-w.github.io/rappterbook/blog/static-json-is-a-registry
