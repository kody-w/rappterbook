# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

RAPP Brainstem is a local-first AI agent server. It's a Flask app that proxies conversation through the GitHub Copilot API with automatic tool-calling via user-defined agents. Single dependency: a GitHub account with Copilot access. Runs on port 7071.

Philosophy: "engine, not experience" — infrastructure only, no opinionated UI or workflows (see CONSTITUTION.md).

## Commands

```bash
# Start server
./start.sh                # macOS/Linux (creates venv, installs deps, runs)
python brainstem.py       # Direct run (assumes deps installed)

# Install dependencies
pip3 install -r requirements.txt

# Run all tests
python3 -m pytest test_local_agents.py -v

# Run a single test
python3 -m pytest test_local_agents.py::TestLocalStorage::test_write_and_read -v
```

No build step, linter, or type checker is configured.

## Architecture

**Entry point:** `brainstem.py` — a single-file Flask server (~1100 lines) that handles auth, chat, agent orchestration, and the web UI.

**Request flow (POST /chat):**
1. Load `soul.md` (system prompt) and fresh-discover agents from `agents/`
2. Build OpenAI-format tool definitions from agent metadata
3. Call GitHub Copilot API with system prompt + conversation history + tools
4. If the LLM returns tool calls, execute agent `.perform()` methods and loop (up to 3 rounds)
5. Return final response + `agent_logs`

**Agent system:**
- Auto-discovered via glob `agents/*_agent.py` (flat directory only — `agents/experimental/` is intentionally excluded)
- Each agent is a Python class extending `BasicAgent` with `metadata` (OpenAI function schema) and `perform(**kwargs)` method
- Optional `system_context()` injects text into the system prompt every turn
- Agents are reloaded from disk on every request — edit and test without restart
- Missing pip dependencies are auto-installed at import time

**Local storage shim** (`local_storage.py`): Agents import `from utils.azure_file_storage import AzureFileStorageManager` — brainstem intercepts via `sys.modules` and provides a local JSON-file implementation under `.brainstem_data/`. This enables transparent migration to Azure later.

**Auth chain:** `GITHUB_TOKEN` env var → `.copilot_token` file (device-code OAuth) → `gh auth token` CLI. The GitHub token is exchanged for a short-lived Copilot API token, cached in `.copilot_session` with auto-refresh.

## Key Files

| File | Purpose |
|------|---------|
| `brainstem.py` | Main server: all routes, agent loading, Copilot API integration |
| `basic_agent.py` | Base class for agents (also copied to `agents/basic_agent.py`) |
| `local_storage.py` | Local shim for Azure File Storage |
| `soul.md` | Default system prompt loaded every request |
| `index.html` | Built-in web UI served at `/` |
| `VERSION` | Semantic version string (currently 0.4.0) |
| `CONSTITUTION.md` | Governance doc defining what belongs in this repo |

## Writing Agents

Agents must:
- Live in `agents/` with filename matching `*_agent.py`
- Define a class extending `BasicAgent` with `metadata` dict (OpenAI function-calling schema) and `perform(**kwargs)` returning a string
- Use `self.metadata["description"]` to tell the LLM when to invoke the agent

The `agents/experimental/` subdirectory exists for agents that should not be auto-loaded.

## Environment

Configuration via `.env` (auto-created from `.env.example` by `start.sh`):
- `GITHUB_TOKEN` — auto-detected from `gh` CLI if blank
- `GITHUB_MODEL` — default `gpt-4o`, switchable at runtime via `/models/set`
- `SOUL_PATH`, `AGENTS_PATH`, `PORT`, `VOICE_MODE`
