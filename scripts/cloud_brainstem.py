#!/usr/bin/env python3
from __future__ import annotations

"""Cloud Brainstem — single-tick orchestrator that consolidates chore workflows.

One GitHub Actions cron fires this every 30 minutes. Each tick discovers
chore agents (scripts/brainstem/agents/*_chore_agent.py — AGENT["_meta"]["category"] == "chore")
and runs them in priority order. All state writes from a single tick collapse
into ONE git commit, replacing the 5-30+ commits/hour pattern of the current
multi-workflow setup.

Phase 1 scope: scaffold only. Runs ALONGSIDE existing workflows — does NOT
replace them. Verify parity for 24-48h, then disable old crons one by one.

Exit code 0 unless the orchestrator itself crashes. Individual chore failures
are recorded in the log but do not fail the workflow.

The brainstem always runs LIVE — no dry-run mode. Intelligence is provided
by GitHub Copilot CLI (via RAPPTERBOOK_LLM_BACKEND=copilot in the workflow).

Usage:
    python scripts/cloud_brainstem.py                 # full tick, all chores
    python scripts/cloud_brainstem.py --only janitor  # one chore by name
    python scripts/cloud_brainstem.py --list          # list discovered chores
"""

import argparse
import json
import logging
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from state_io import load_json, save_json, now_iso  # noqa: E402

STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))
AGENTS_DIR = SCRIPTS / "brainstem" / "agents"
LOG_PATH = STATE_DIR / "cloud_brainstem_log.json"

logger = logging.getLogger("cloud_brainstem")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def discover_chore_agents() -> list[dict]:
    """Discover chore agents and sort by AGENT._meta.priority ascending.

    Returns a list of {"name", "agent", "run", "path"} dicts.
    """
    from brainstem.rappter_agent import load_agents_from_dir

    all_agents = load_agents_from_dir(AGENTS_DIR)
    chores = []
    for name, data in all_agents.items():
        meta = (data.get("agent") or {}).get("_meta") or {}
        if meta.get("category") == "chore":
            data["_priority"] = int(meta.get("priority", 100))
            data["_name"] = name
            chores.append(data)
    chores.sort(key=lambda d: (d["_priority"], d["_name"]))
    return chores


def build_context() -> dict:
    """Build a minimal context dict that chores can read.

    Kept intentionally small — chores load their own state via state_io.
    """
    return {
        "tick_started_at": now_iso(),
        "state_dir": str(STATE_DIR),
        "root": str(ROOT),
        "actor": "cloud-brainstem",
    }


def run_chore(chore: dict, context: dict) -> dict:
    """Run one chore agent and return a structured result entry."""
    name = chore["_name"]
    started = time.time()
    entry: dict = {
        "chore": name,
        "started_at": now_iso(),
        "priority": chore["_priority"],
    }
    try:
        result = chore["run"](context)
        entry["status"] = result.get("status", "ok")
        entry["result"] = result
    except Exception as exc:
        entry["status"] = "error"
        entry["error"] = f"{type(exc).__name__}: {exc}"
        entry["traceback"] = traceback.format_exc()
        logger.exception("Chore %s crashed", name)
    entry["duration_sec"] = round(time.time() - started, 2)
    return entry


def append_log(tick: dict, keep: int = 200) -> None:
    """Append the tick log to state/cloud_brainstem_log.json (rolling)."""
    log = load_json(LOG_PATH) or {}
    history = log.get("history") or []
    history.append(tick)
    if len(history) > keep:
        history = history[-keep:]
    log["history"] = history
    log["_meta"] = {
        "last_tick": tick["finished_at"],
        "total_ticks": log.get("_meta", {}).get("total_ticks", 0) + 1,
        "consolidates_workflows": tick.get("consolidates", []),
    }
    save_json(LOG_PATH, log)


def list_chores() -> int:
    """Print discovered chores and exit."""
    chores = discover_chore_agents()
    print(f"Discovered {len(chores)} chore agent(s):")
    for c in chores:
        meta = c["agent"]
        consolidates = meta.get("_meta", {}).get("consolidates", [])
        print(f"  [{c['_priority']:>3}] {c['_name']:<25} -> {meta.get('description', '')}")
        if consolidates:
            print(f"        consolidates: {', '.join(consolidates)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Cloud brainstem — single-tick chore orchestrator")
    parser.add_argument("--only", type=str, help="Run only the named chore (e.g. 'janitor', 'heartbeat')")
    parser.add_argument("--list", action="store_true", help="List discovered chore agents and exit")
    args = parser.parse_args()

    if args.list:
        return list_chores()

    chores = discover_chore_agents()
    if args.only:
        chores = [c for c in chores if c["_name"] == args.only]
        if not chores:
            print(f"No chore named {args.only!r}. Use --list to see options.", file=sys.stderr)
            return 2

    if not chores:
        print("No chore agents discovered.", file=sys.stderr)
        return 0

    backend = os.environ.get("RAPPTERBOOK_LLM_BACKEND", "<default>")
    context = build_context()
    tick: dict = {
        "tick_id": context["tick_started_at"],
        "started_at": context["tick_started_at"],
        "llm_backend": backend,
        "chores_run": [],
        "consolidates": [],
    }

    logger.info("Cloud brainstem tick starting (chores=%d, llm=%s)", len(chores), backend)

    for chore in chores:
        logger.info("→ %s (priority=%d)", chore["_name"], chore["_priority"])
        entry = run_chore(chore, context)
        tick["chores_run"].append(entry)
        meta = (chore["agent"].get("_meta") or {})
        tick["consolidates"].extend(meta.get("consolidates") or [])
        status_glyph = "ok" if entry["status"] == "ok" else "ERR"
        logger.info("  [%s] %s in %.2fs", status_glyph, chore["_name"], entry["duration_sec"])

    tick["finished_at"] = now_iso()
    tick["successful"] = sum(1 for e in tick["chores_run"] if e["status"] == "ok")
    tick["failed"] = sum(1 for e in tick["chores_run"] if e["status"] != "ok")

    append_log(tick)

    print(json.dumps({
        "tick_id": tick["tick_id"],
        "successful": tick["successful"],
        "failed": tick["failed"],
        "chores": [{"name": e["chore"], "status": e["status"]} for e in tick["chores_run"]],
    }, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
