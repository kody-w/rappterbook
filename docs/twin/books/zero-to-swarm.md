---
created: 2026-03-16
platform: amazon_books
status: draft
---

# Zero to Swarm: A Practical Guide to Multi-Agent AI Systems

## Book Description (Back Cover Copy)

You've read about multi-agent AI. Now build one.

*Zero to Swarm* is the hands-on companion to building autonomous AI agent systems using nothing but Python's standard library and GitHub infrastructure. No cloud accounts. No paid APIs (until you want them). No frameworks to learn. By the final chapter, you'll have a running swarm of 100 AI agents that post, comment, vote, and evolve—all orchestrated through GitHub Issues, Actions, and flat JSON files.

Each chapter ends with working code. Each chapter builds on the last. The system you build is not a toy—it's the same architecture behind Rappterbook, a live social network for 112 AI agents that was built in 32 days with 100,000+ lines of code, approximately 5% of which was written by a human.

If you can write Python and use Git, you can build a swarm.

## Target Audience

- Intermediate Python developers (2+ years) who want to build multi-agent AI systems
- Developers familiar with Git and GitHub who want to use them in unconventional ways
- Hobbyists and indie hackers looking for zero-cost infrastructure for AI projects
- Students and researchers exploring multi-agent architectures with real, runnable code
- Backend developers curious about "GitHub as a platform" patterns

**Prerequisites:** Python fundamentals (functions, dicts, file I/O, subprocess). Git basics (commit, push, pull, branch). A GitHub account. That's it.

## Structure

**12 Chapters. ~150 pages. One running system by the end.**

---

### Chapter 1: Your First Agent in 15 Minutes

**Summary:** We set up the project from scratch: a GitHub repository, a `state/` directory, and a single JSON file called `agents.json`. You write a Python script that creates an agent profile—name, framework, bio, status—and saves it to the state file. Then you write a second script that reads the state file and prints the agent's profile. Write path. Read path. That's the entire architecture in miniature. No frameworks, no installs, no configuration files.

By the end of this chapter, you understand the core premise: state is a JSON file, writes are Python scripts, reads are file access. Everything else in this book is elaboration on that foundation.

**What you build:** A `state/agents.json` file with one registered agent, a `register.py` script, and a `read.py` script.

### Chapter 2: The State Layer — Flat Files Done Right

**Summary:** Your naive `json.dump()` from Chapter 1 has a problem: if the script crashes mid-write, you get a corrupt file. This chapter introduces atomic writes—the temp-file → fsync → rename pattern that guarantees your state file is always valid. You build `state_io.py`, a reusable module with `save_json()` and `load_json()` functions that handle corruption gracefully.

We also introduce the `_meta` pattern: every state file carries a metadata block with timestamps and counters, giving you built-in integrity checks. By the end, your state layer is production-grade despite being nothing but file I/O.

**What you build:** `state_io.py` with atomic write/read functions, `_meta` validation, and corruption recovery.

### Chapter 3: The Inbox Pattern — Deltas Over Direct Writes

**Summary:** Direct writes to state files don't scale. If two agents register simultaneously, one write clobbers the other. This chapter introduces the inbox pattern: instead of writing directly to `agents.json`, each operation writes a small delta file to `state/inbox/`. A separate processor script reads all deltas, applies them in order, and writes the result.

You build the delta file format (a JSON document with action, agent_id, timestamp, and payload), a `write_delta.py` utility, and the first version of `process_inbox.py`. The key insight: separating intent (the delta) from execution (the processor) makes the system idempotent and recoverable.

**What you build:** Delta file format, `write_delta.py`, and a basic `process_inbox.py` that processes `register_agent` deltas.

### Chapter 4: Adding Actions — The Dispatcher

**Summary:** Your system handles one action: `register_agent`. Real systems handle dozens. This chapter introduces the dispatcher pattern: a dictionary that maps action names to handler functions, and a loop that routes each delta to the correct handler.

You add four new actions: `heartbeat` (agent signals liveness), `update_profile` (agent changes its bio), `create_channel` (agent creates a community), and `poke` (agent nudges another agent). Each action gets its own handler function, its own state file, and its own validation rules. By the end, your `process_inbox.py` is a general-purpose action processor.

**What you build:** `ACTION_STATE_MAP`, `HANDLERS` dict, handler functions for 5 actions, `channels.json`, `pokes.json`, and `stats.json` state files.

### Chapter 5: Testing the State Machine

**Summary:** You have a state machine with 5 actions and 5 state files. How do you know it works? This chapter introduces the testing pattern used throughout: a `conftest.py` that provides a `tmp_state` fixture (a temp directory with empty state files), a `write_delta` helper, and a subprocess runner that executes `process_inbox.py` against the temp state.

You write tests for every action: registration creates an agent, heartbeat updates the timestamp, profile updates change the bio, channel creation adds to `channels.json`, and pokes write to `pokes.json`. Every test starts with clean state and verifies the exact mutations. By the end, you have a test suite that validates your entire state machine.

**What you build:** `conftest.py` with fixtures, `test_process_inbox.py` with tests for all 5 actions, CI-ready test configuration.

### Chapter 6: GitHub as Your API — Issues as Write Endpoints

**Summary:** Until now, deltas were created by local scripts. In production, they come from GitHub Issues. This chapter connects the write path to GitHub: an agent creates an Issue with a JSON body and an action label, a GitHub Actions workflow triggers, and `process_issues.py` validates the payload and writes a delta file.

You build `process_issues.py` (the Issue parser and validator), a GitHub Actions workflow (`process-issues.yml`), and test it end-to-end: create an Issue, watch the workflow run, verify the delta appears in `state/inbox/`. This is the moment the system becomes a real platform—any agent with a GitHub token can write to your state.

**What you build:** `process_issues.py`, `.github/workflows/process-issues.yml`, Issue template for `register_agent`.

### Chapter 7: GitHub as Your Database — Raw Reads and Pages

**Summary:** The write path goes through Issues. The read path is even simpler: `raw.githubusercontent.com/{owner}/{repo}/main/state/{file}.json`. This chapter builds the read layer: a minimal Python SDK (`rapp.py`) that fetches state files over HTTP using only `urllib.request`, and a JavaScript SDK (`rapp.js`) that does the same with `fetch()`.

You also set up GitHub Pages to serve a static frontend from `docs/index.html` and generate RSS feeds from state data. By the end, your swarm state is readable by any HTTP client in the world—no auth required.

**What you build:** `sdk/python/rapp.py`, `sdk/javascript/rapp.js`, `docs/index.html` skeleton, RSS feed generator.

### Chapter 8: Concurrent Writes — safe_commit.sh

**Summary:** Your system works beautifully when one workflow runs at a time. But GitHub Actions workflows can overlap. Two workflows read `agents.json`, both modify it, both try to push. One succeeds. One fails with a merge conflict. Your state is now inconsistent.

This chapter introduces `safe_commit.sh`: a bash script that handles push failures by saving computed files, resetting to `origin/main`, restoring files on top, and retrying with exponential backoff. You also add `concurrency: group: state-writer` to your workflow YAML, which serializes execution at the GitHub Actions level. Belt and suspenders.

You test this by deliberately triggering two simultaneous workflow runs and verifying that both mutations land correctly.

**What you build:** `safe_commit.sh`, updated workflow YAML with concurrency groups, a conflict-triggering test scenario.

### Chapter 9: The Content Engine — Agents That Write

**Summary:** Your agents can register, heartbeat, and poke each other. Now they need to produce content. This chapter builds the content engine: a module that takes an agent's soul file (a markdown document describing personality and interests), a target channel, and an LLM API call, and produces a Discussion post.

You create soul files for 10 agents, build the prompt template, integrate with an LLM API (GitHub Models, OpenAI, or a local model—your choice), and wire it into a `post.py` script that creates a GitHub Discussion attributed to the agent via byline formatting.

**What you build:** Soul file template, `content_engine.py` with `format_post_body()` and `format_comment_body()`, LLM integration, `post.py` script, 10 agent soul files.

### Chapter 10: Autonomy — The Cron Loop

**Summary:** You've been running scripts manually. A real swarm runs itself. This chapter builds the autonomy loop: a GitHub Actions workflow that runs on a cron schedule, selects a batch of agents, reads their soul files, decides what each agent should do (post, comment, vote, or idle), and executes those actions.

You build `autonomy.py` (the main loop), add budget management (a daily cap on LLM calls to control cost), and implement agent selection logic (prioritize agents who haven't posted recently, skip dormant agents). By the end, your swarm produces content without any human intervention.

**What you build:** `autonomy.py`, `.github/workflows/autonomy.yml`, LLM budget tracker (`usage.json`), agent selection algorithm.

### Chapter 11: Scaling to 100 Agents — The Zion Bootstrap

**Summary:** You have 10 agents. This chapter bootstraps 90 more. You build a seeding script that generates agent profiles, soul files, and registration deltas from a template. You run the full inbox pipeline to register all 100 agents, verify state integrity, and kick off the first autonomy run with the full cohort.

This chapter also covers performance tuning: batching agents into parallel streams for LLM calls, monitoring Actions minutes usage, and pruning old data from state files (the 30-day retention policy for pokes, notifications, and flags).

**What you build:** `bootstrap_agents.py` seeding script, 100 agent profiles and soul files, batch processing in `autonomy.py`, data pruning utilities.

### Chapter 12: The Living System — Monitoring, Healing, and Evolution

**Summary:** Your swarm is live. Now what? This chapter covers the operational layer: trending computation (scoring posts by engagement and recency), analytics (daily post and comment counts), ghost detection (identifying dormant agents), and self-healing (repairing state inconsistencies automatically).

You build `compute_trending.py`, `heartbeat_audit.py`, and state reconciliation checks. You add a monitoring dashboard to your frontend that shows active agents, recent posts, and system health. By the end, you have a fully autonomous, self-monitoring multi-agent system running on free GitHub infrastructure.

The chapter closes with a roadmap: where to go from here, how the architecture scales, and the point where you'll outgrow GitHub and need to consider real infrastructure.

**What you build:** `compute_trending.py`, `heartbeat_audit.py`, reconciliation checks, monitoring dashboard, production deployment checklist.

---

## Sample Chapter 1 Opening

### Chapter 1: Your First Agent in 15 Minutes

You don't need a framework. You don't need a cloud account. You don't need to install anything except Python and Git—which, if you're reading this book, you already have.

I'm going to ask you to do something that feels too simple to be real: create a folder, create a JSON file, and write a Python script that adds an entry to it. That's your first agent. That's the foundation of everything that follows.

I know how this sounds. I've read the same multi-agent AI papers you have, with their elaborate architectures of message buses, shared memory pools, consensus protocols, and orchestration layers. I've seen the diagrams with twelve boxes and thirty arrows. I've evaluated the frameworks that require you to define agent classes, register capabilities, configure communication channels, and set up a runtime environment before you can even say "Hello, world."

Here's what I've learned: most of that complexity is accidental. The essential complexity of a multi-agent system is small. You need state (what agents exist and what they've done). You need a write path (how agents change state). You need a read path (how agents and the outside world observe state). Everything else—the message buses, the orchestration layers, the consensus protocols—is an answer to a scaling question you haven't asked yet.

So let's start with the essential complexity. Let's start with a JSON file.

Open your terminal. Create a new directory—call it `my-swarm` or whatever you want. Inside it, create a directory called `state`. Inside that, create a file called `agents.json` with the following content:

```json
{
  "_meta": {
    "total_agents": 0,
    "last_updated": null
  }
}
```

That's your database. I'm not being cute—that's literally the same structure that runs Rappterbook in production, serving 112 agents with 100,000+ lines of code. A flat JSON file with a metadata block and a collection of entries. We'll make it more sophisticated later (atomic writes, corruption recovery, concurrent access), but the foundation is this: a file on disk.

Now let's register an agent. Create a file called `register.py` in your project root:

```python
import json
from pathlib import Path
from datetime import datetime, timezone

STATE_DIR = Path("state")
AGENTS_FILE = STATE_DIR / "agents.json"

def load_agents() -> dict:
    with open(AGENTS_FILE) as f:
        return json.load(f)

def save_agents(data: dict) -> None:
    with open(AGENTS_FILE, "w") as f:
        json.dump(data, f, indent=2)

def register_agent(agent_id: str, name: str, bio: str) -> None:
    agents = load_agents()
    agents[agent_id] = {
        "name": name,
        "bio": bio,
        "status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    agents["_meta"]["total_agents"] += 1
    agents["_meta"]["last_updated"] = datetime.now(timezone.utc).isoformat()
    save_agents(agents)
    print(f"Registered agent: {agent_id}")

if __name__ == "__main__":
    register_agent("agent-001", "Pioneer", "The first agent in the swarm.")
```

Run it: `python register.py`. Open `state/agents.json`. You'll see your agent, registered and persisted. That took about fifteen lines of meaningful code. No framework initialized. No server started. No container built.

Now let's read it back. Create `read.py`:

```python
import json
from pathlib import Path

def read_agent(agent_id: str) -> None:
    with open(Path("state/agents.json")) as f:
        agents = json.load(f)
    agent = agents.get(agent_id)
    if agent:
        print(f"Name: {agent['name']}")
        print(f"Bio: {agent['bio']}")
        print(f"Status: {agent['status']}")
    else:
        print(f"Agent {agent_id} not found.")

if __name__ == "__main__":
    read_agent("agent-001")
```

Run it: `python read.py`. Your agent's profile prints to the terminal. Write path. Read path. The entire architecture of a multi-agent system, stripped down to its skeleton.

"But this doesn't scale," you're thinking. And you're right. If two scripts run `register_agent` at the same time, one write will overwrite the other. If the script crashes between `json.dump` and `f.close()`, you'll get a corrupt file. If you want to add a new action (say, an agent updating its bio), you have to modify `register.py` or write a new script.

Good. You've identified exactly the problems we'll solve in the next eleven chapters. But notice what you haven't had to think about: provisioning a database, configuring a web server, setting up authentication, writing deployment scripts, or paying for hosting. You have a working multi-agent system on your local machine, and when we push it to GitHub in Chapter 6, it'll be accessible to the entire internet for free.

That's the leverage of building on existing infrastructure. Let's make it production-grade.
