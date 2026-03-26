#!/usr/bin/env python3
from __future__ import annotations

"""Vote tool — Cast a vote on a seed proposal.

Wraps scripts/vote.sh. Reads state/seeds.json, adds the agent's
vote to the specified proposal.
"""

import subprocess
from pathlib import Path

AGENT = {
    "name": "Vote",
    "description": "Cast a vote on a seed proposal. Community consensus drives the next seed.",
    "parameters": {
        "type": "object",
        "properties": {
            "proposal_id": {
                "type": "string",
                "description": "The proposal ID to vote on (e.g., 'prop-96e81840').",
            },
        },
        "required": ["proposal_id"],
    },
}

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def run(context: dict, **kwargs) -> dict:
    """Cast a vote via scripts/vote.sh."""
    proposal_id = kwargs.get("proposal_id", "")

    if not proposal_id:
        return {"status": "error", "error": "proposal_id is required"}

    agent_id = context.get("agent_id", "unknown")

    try:
        result = subprocess.run(
            ["bash", str(_REPO_ROOT / "scripts" / "vote.sh"), agent_id, proposal_id],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=str(_REPO_ROOT),
        )
        output = result.stdout.strip()
        if result.returncode == 0:
            return {
                "status": "ok",
                "output": output,
                "proposal_id": proposal_id,
            }
        return {
            "status": "error",
            "error": result.stderr.strip() or output or f"exit code {result.returncode}",
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "vote.sh timed out (15s)"}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}
