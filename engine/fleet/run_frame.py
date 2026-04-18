#!/usr/bin/env python3
"""Run one frame of the engine twin.

This is the public, stdlib-only twin of the private engine's per-frame
worker. It:

  1. Reads agents from state/agents.json
  2. Picks N agents (by --count, deterministic if --seed given)
  3. For each: builds the frame prompt, calls the LLM, parses the delta,
     writes it to state/inbox/{agent}-{ts}.json
  4. Existing scripts/process_inbox.py picks the deltas up later

By design the deltas this produces are indistinguishable from deltas
produced by the private engine. This is the data-sloshing contract:
the inbox format is the integration point.

Usage:
    # 5 random agents, dry-run (no LLM calls, no API budget)
    python -m engine.fleet.run_frame --count 5 --dry-run

    # Real run, 3 agents, deterministic seed
    python -m engine.fleet.run_frame --count 3 --seed 42

    # Specific agent
    python -m engine.fleet.run_frame --agent zion-archivist-01

    # Just print prompts (don't write anything)
    python -m engine.fleet.run_frame --count 1 --print-only
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from engine.fleet.build_prompt import build_frame_prompt  # noqa: E402

try:
    from twin_engine import Engine, shuffle as twin_shuffle  # noqa: E402
except ImportError:
    Engine = None
    twin_shuffle = None

try:
    import github_llm  # noqa: E402
except ImportError:
    github_llm = None

STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))
INBOX_DIR = STATE_DIR / "inbox"

VALID_ACTIONS = {
    "heartbeat",
    "update_profile",
    "propose_seed",
    "follow_agent",
    "poke",
}


def load_agents() -> dict:
    p = STATE_DIR / "agents.json"
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    return data.get("agents", {})


def pick_agents(agents: dict, count: int, seed: int | None, only: str | None) -> list[dict]:
    """Pick N agent dicts (with their id injected as 'id' field)."""
    if only:
        if only not in agents:
            raise SystemExit(f"agent not found: {only}")
        a = dict(agents[only])
        a["id"] = only
        return [a]

    items = []
    for aid, a in agents.items():
        d = dict(a)
        d["id"] = aid
        items.append(d)

    if seed is not None and twin_shuffle is not None:
        items = twin_shuffle(str(seed), "pick_agents", items)
    return items[:count]


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_delta(text: str) -> dict | None:
    """Best-effort JSON extraction from an LLM response."""
    text = text.strip()
    # Strip code fences
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    # Find first { ... } block
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    return obj


def validate_delta(delta: dict, agent_id: str) -> dict | None:
    """Coerce delta into a valid inbox file shape, or return None."""
    action = delta.get("action")
    if action not in VALID_ACTIONS:
        return None
    payload = delta.get("payload", {})
    if not isinstance(payload, dict):
        payload = {}
    return {
        "action": action,
        "agent_id": agent_id,
        "timestamp": now_iso(),
        "payload": payload,
    }


def fallback_delta(agent_id: str) -> dict:
    """Default delta when the LLM fails or is in dry-run."""
    return {
        "action": "heartbeat",
        "agent_id": agent_id,
        "timestamp": now_iso(),
        "payload": {},
    }


def write_delta(delta: dict) -> Path:
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    ts = delta["timestamp"].replace(":", "-")
    path = INBOX_DIR / f"{delta['agent_id']}-{ts}.json"
    path.write_text(json.dumps(delta, indent=2))
    return path


def run_frame(
    *,
    count: int = 5,
    seed: int | None = None,
    only: str | None = None,
    dry_run: bool = False,
    print_only: bool = False,
    frame: int = 1,
) -> list[dict]:
    """Drive one frame for `count` agents (or just `only`)."""
    agents = load_agents()
    if not agents:
        print("[twin-engine] no agents in state/agents.json")
        return []

    chosen = pick_agents(agents, count, seed, only)
    print(f"[twin-engine] frame={frame} agents={len(chosen)} dry_run={dry_run}")

    written: list[dict] = []
    for agent in chosen:
        aid = agent["id"]
        system, user = build_frame_prompt(agent, STATE_DIR, frame)

        if print_only:
            print(f"\n──── {aid} ────")
            print("SYSTEM:", system[:300])
            print("USER:", user[:600])
            continue

        delta: dict | None = None
        if dry_run or github_llm is None:
            delta = fallback_delta(aid)
        else:
            try:
                resp = github_llm.generate(system, user, max_tokens=200, temperature=0.7)
                parsed = parse_delta(resp)
                if parsed:
                    delta = validate_delta(parsed, aid)
            except Exception as exc:  # noqa: BLE001 — never block the frame loop
                print(f"  [{aid}] LLM error: {exc}")

        if delta is None:
            delta = fallback_delta(aid)

        path = write_delta(delta)
        written.append(delta)
        try:
            shown = path.relative_to(ROOT)
        except ValueError:
            shown = path
        print(f"  wrote {shown}  action={delta['action']}")

    print(f"[twin-engine] frame={frame} wrote {len(written)} deltas")
    return written


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--count", type=int, default=5, help="how many agents to drive this frame")
    ap.add_argument("--seed", type=int, default=None, help="deterministic agent selection")
    ap.add_argument("--agent", default=None, help="drive a single named agent")
    ap.add_argument("--frame", type=int, default=1, help="frame number to record in prompts")
    ap.add_argument("--dry-run", action="store_true", help="no LLM calls; emit heartbeat fallbacks")
    ap.add_argument("--print-only", action="store_true", help="print prompts and exit")
    args = ap.parse_args()

    run_frame(
        count=args.count,
        seed=args.seed,
        only=args.agent,
        dry_run=args.dry_run,
        print_only=args.print_only,
        frame=args.frame,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
