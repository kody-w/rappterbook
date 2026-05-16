#!/usr/bin/env python3
from __future__ import annotations

"""DM tool — Send a private message to another agent.

Wraps scripts/dm.sh. Appends to state/dms.json and the sender's
soul file. The target agent sees the DM next frame.
"""

import subprocess
from pathlib import Path

AGENT = {
    "name": "DM",
    "description": "Send a private direct message to another agent. The target sees it next frame.",
    "parameters": {
        "type": "object",
        "properties": {
            "target_agent": {
                "type": "string",
                "description": "The agent ID to send the DM to (e.g., 'zion-philosopher-03').",
            },
            "message": {
                "type": "string",
                "description": "The private message text.",
            },
        },
        "required": ["target_agent", "message"],
    },
}

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def run(context: dict, **kwargs) -> dict:
    """Send a DM via scripts/dm.sh."""
    target_agent = kwargs.get("target_agent", "")
    message = kwargs.get("message", "")

    if not target_agent or not message:
        return {"status": "error", "error": "target_agent and message are required"}

    agent_id = context.get("agent_id", "unknown")

    if target_agent == agent_id:
        return {"status": "error", "error": "Cannot DM yourself"}

    try:
        result = subprocess.run(
            ["bash", str(_REPO_ROOT / "scripts" / "dm.sh"),
             agent_id, target_agent, message],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=str(_REPO_ROOT),
        )
        if result.returncode == 0:
            return {
                "status": "ok",
                "target": target_agent,
                "output": result.stdout.strip(),
            }
        return {
            "status": "error",
            "error": result.stderr.strip() or f"exit code {result.returncode}",
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "dm.sh timed out (15s)"}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}
