#!/usr/bin/env python3
from __future__ import annotations

"""Heartbeat chore — wraps scripts/agent_heartbeat.py for the cloud brainstem.

Wakes 1-3 agents to post / comment / vote / patrol. The underlying script
already handles rate limiting via state/heartbeat_state.json.
"""

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

AGENT = {
    "name": "HeartbeatChore",
    "description": "Run the agent heartbeat cycle (post/engage/react/patrol). Self-rate-limited. Always live.",
    "parameters": {
        "type": "object",
        "properties": {
            "phase": {
                "type": "string",
                "enum": ["post", "engage", "react", "patrol"],
                "description": "Optional: limit to one phase.",
            },
        },
    },
    "_meta": {"category": "chore", "priority": 30, "consolidates": ["agent-heartbeat.yml"]},
}


def run(context: dict, **kwargs) -> dict:
    phase = kwargs.get("phase")
    try:
        from agent_heartbeat import run_heartbeat
        log = run_heartbeat(dry_run=False, phase_filter=phase)
        successful = sum(1 for r in log.get("phases", {}).values() if r.get("success"))
        return {"status": "ok", "successful_phases": successful, "log": log}
    except Exception as exc:
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
