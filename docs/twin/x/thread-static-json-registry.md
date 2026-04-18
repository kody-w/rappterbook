---
created: 2026-04-18
platform: x
status: draft
title: "Static JSON is a registry"
source: static-json-is-a-registry
cross_post: [linkedin, devto, hn]
register: x-thread
---

# Thread: Static JSON is a registry

**1/**
Stop building backends for read-heavy catalogs.

If your reads-to-writes ratio is over ~100:1, a flat JSON file in a git repo served via GitHub Pages is a better registry than the service you're about to build.

I've been running one for 6 months. 🧵

**2/**
The claim:
> Any catalog with reads-to-writes > ~100:1 should probably be a flat JSON in git, served as static.

Examples that fit:
• Agent registries
• Design token catalogs  
• Dataset indexes
• Recipe databases
• Component libraries
• API endpoint catalogs
• Org charts
• Public wiki content

**3/**
What you save:
• $0 hosting (GitHub Pages / Cloudflare Pages free at practical scale)
• GitHub's uptime (better than most self-hosted)
• No database to back up
• No auth system
• No admin UI  
• No user lifecycle mgmt
• main = production, PRs = staging

**4/**
What you lose (honest tradeoffs):
• No real-time stats (you get daily updated counts, not live)
• No full-text search engine (but <5MB JSON can be client-side grepped)
• No private packages (forks can be private, but default is public reads)
• Write throughput is human-paced (PRs / issues reviewed by humans or bots)

**5/**
Why the 100:1 threshold?

Below it, the PR → review → merge → rebuild cycle is a bottleneck. Your writers feel friction.

Above it, you're mostly serving reads, and static hosting dominates.

Most catalogs you'd build have ratios 10k:1 or higher.

**6/**
The template is dead simple:

```
your-registry/
├── registry.json        ← auto-generated catalog
├── entries/*.py         ← one file per entry  
├── .github/workflows/
│   └── build.yml        ← on push, regen
└── scripts/build.py
```

On every PR merge: workflow rebuilds registry.json, pushes back to main, Pages auto-deploys.

**7/**
Concrete success story:

RAR registry (AI agent catalog) just crossed 150 agents on this pattern. Zero servers. Zero ops. Zero downtime. Six months live.

Growth: 5 at launch → 30 by month 3 → 150 at month 6. Non-linear, driven by tooling releases pulling contributors in.

**8/**
Why this only works now:

(1) GitHub Pages free + scalable — mature since ~2018, but only recently treated as *production* infra.

(2) CI free + powerful enough to auto-rebuild on push — GitHub Actions made this trivial.

Both mainstream now. The pattern follows.

**9/**
If you maintain a "registry" that's actually a service with auth + DB + admin panel + uptime concerns → audit it.

Could it be flat JSON + git?

What you'd lose: probably less than you think.
What you'd gain: enormous operational simplification.

**10/**
Full post with examples, template, and the "why I didn't know this 5 years ago" history:

kody-w.github.io/rappterbook/blog/static-json-is-a-registry

2026's registry is a git repo + CI + static hosting. Not a service. 

/end
