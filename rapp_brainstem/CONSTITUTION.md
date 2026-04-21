# RAPP Brainstem — Constitution

> *The principles that govern this project. Read this before you contribute.*

---

## What This Is

RAPP Brainstem is a **business-focused AI agent platform** that teaches
the Microsoft AI stack through progressive tiers. It is an engine —
not a consumer product, not a toy, not a creature.

It exists to help developers, teams, and organizations build AI agents
that start local and scale to Azure and M365 Copilot Studio.

---

## Article I — The Engine, Not the Experience

RAPP Brainstem is infrastructure. It is the Flask server, the LLM loop,
the agent discovery, the auth chain, and the deployment templates.

It does not have a personality out of the box beyond what the user puts
in their soul file. It does not have a brand identity beyond "RAPP
Brainstem." It does not anthropomorphize itself.

Consumer-facing experiences (creatures, organisms, educational platforms,
children's content) are **separate intellectual property** and belong in
their own repositories. They may use the brainstem as their engine, but
they do not live here.

---

## Article II — Three Tiers, One Path

The platform teaches the Microsoft AI stack one layer at a time:

| Tier | Name | What It Is | What You Learn |
|------|------|-----------|----------------|
| 1 | **Brainstem** | Local Flask server + GitHub Copilot | Python agents, function-calling, prompt engineering |
| 2 | **Spinal Cord** | Azure deployment (ARM template) | Azure Functions, Azure OpenAI, managed identity, RBAC |
| 3 | **Nervous System** | Copilot Studio + M365 | Power Platform, declarative agents, Teams integration |

Each tier is self-contained and complete. Users advance when they choose
to, not when we push them.

---

## Article III — Local First

The brainstem runs on the user's machine. No cloud account required.
No API keys beyond a GitHub account with Copilot access.

Azure and Copilot Studio are deployment targets, not prerequisites. A
brainstem that never leaves localhost is fully functional.

All local data (memories, config, agents) stays on the user's device
unless they explicitly deploy to a higher tier.

---

## Article IV — One File, One Agent

Agents are single `*_agent.py` files that extend `BasicAgent` and
implement `perform()`. That's the entire contract.

- No config files. No YAML. No dependency manifests.
- Auto-discovered on startup. No registration step.
- The LLM decides when to call them based on the metadata description.
- Portable: copy the file, the skill travels with it.

Complexity belongs inside the agent's `perform()` method, not in the
framework around it. The surface area stays small so anyone can read,
write, and share agents.

---

## Article V — Don't Break the One-Liner

The install experience is sacred:

```bash
curl -fsSL https://kody-w.github.io/rapp-installer/install.sh | bash
```

```powershell
irm https://raw.githubusercontent.com/kody-w/rapp-installer/main/install.ps1 | iex
```

One command. Works on a fresh machine. Installs prerequisites, clones
the repo, sets up the venv, authenticates, and launches.

The same principle applies to every tier:

- **Brainstem:** `curl ... install.sh | bash` — installs and starts
- **Hippocampus:** `curl ... community_rapp/install.sh | bash` — installs and starts

The one-liner IS the onboarding. Everything after it — starting,
authenticating, deploying to Azure — either happens automatically
or is guided by the running system. Manual steps exist only as
advanced documentation, never as the primary path.

When training users, the instruction is: "run the one-liner." That's it.
Any change to the repo must be tested against this path. If the
one-liner breaks, nothing else matters.

---

## Article VI — Scope Discipline

This repository contains:

- ✅ The brainstem server (`brainstem.py`)
- ✅ The default soul file (`soul.md`)
- ✅ The local storage shim (`local_storage.py`)
- ✅ Built-in agents (`agents/`)
- ✅ Azure deployment (`azuredeploy.json`, `deploy.sh`)
- ✅ Power Platform solution (`.zip`)
- ✅ Install scripts (`install.sh`, `install.ps1`, `install.cmd`)
- ✅ Landing page (`index.html`, `docs/`)

This repository does **not** contain:

- ❌ Consumer brand identities (creatures, mascots, organisms)
- ❌ Educational platforms (academies, courses, children's content)
- ❌ Background daemons or heartbeat loops
- ❌ Features that require processes beyond the Flask server
- ❌ Content belonging to other intellectual properties (e.g., openrappter)

When in doubt: if it's not the engine or its deployment path, it
belongs somewhere else.

---

## Article VII — The User Owns Their Instance

- The soul file is theirs to edit. We provide a default, not a mandate.
- The agents directory is theirs to fill. We provide examples, not a locked set.
- The `.env` file is theirs to configure. We provide defaults, not requirements.
- The code is readable because they should understand what's running on their machine.

We never phone home, collect telemetry, or require accounts beyond
GitHub. The user's brainstem is their brainstem.

---

## Article VIII — Universal Platform Gateway

The `rapp-installer` repo is the **single entry point** for the entire RAPP platform. Users start where they want — not where we tell them to.

### Two One-Liners, One Platform

| Path | What It Creates | One-Liner |
|------|----------------|-----------|
| **Brainstem** (Tier 1) | Local Flask AI server at `~/.brainstem/` | `curl -fsSL .../install.sh \| bash` |
| **Hippocampus** (Tier 2) | Azure Functions project at `~/rapp-projects/{name}/` | `curl -fsSL .../community_rapp/install.sh \| bash` |

Both paths are self-contained. Neither depends on the other. A user who starts with the Hippocampus never needs the Brainstem, and vice versa.

### Rules

1. **The brainstem installer stays untouched.** `install.sh` and `install.ps1` at the repo root are the brainstem's sacred one-liners. The Hippocampus installer lives in `community_rapp/` — a parallel path, not a modification of the existing one.

2. **No cross-contamination.** The brainstem install never pulls CommunityRAPP code. The Hippocampus install never pulls brainstem code. They share a repo for discoverability, not for dependency.

3. **Users choose their entry point.** The README and landing page present both paths equally. We never push users from one tier to another — they move when they're ready.

4. **Each path works on a fresh machine.** Prerequisites (Python, Git, Azure Functions Core Tools) are auto-installed. No prior setup assumed.

5. **The Hippocampus is public.** CommunityRAPP is an open-source repo. The Hippocampus installer uses `git clone` (not `gh clone`). No GitHub authentication is required to create a project.

---

## Article IX — Amendments

This constitution can be amended. The only rule: the change must serve
the platform's purpose as a business-focused AI agent engine. If it
blurs the line between engine and experience, it doesn't belong here.

---

*Ratified for RAPP Brainstem. The engine that powers what others build.*
