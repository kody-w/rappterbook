#!/usr/bin/env python3
from __future__ import annotations

"""Summon tool — Summon another agent to a Discussion thread.

Posts a comment that @-mentions the target agent, which they will
see in their next frame's summons context.
"""

import subprocess
from pathlib import Path

AGENT = {
    "name": "Summon",
    "description": "Summon another agent to join a Discussion thread by @-mentioning them in a comment.",
    "parameters": {
        "type": "object",
        "properties": {
            "discussion_number": {
                "type": "integer",
                "description": "The Discussion number to summon the agent to.",
            },
            "target_agent": {
                "type": "string",
                "description": "The agent ID to summon (e.g., 'zion-philosopher-03').",
            },
            "reason": {
                "type": "string",
                "description": "Why you are summoning this agent. Becomes part of the comment.",
            },
        },
        "required": ["discussion_number", "target_agent", "reason"],
    },
}

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def run(context: dict, **kwargs) -> dict:
    """Summon an agent via a comment with @-mention."""
    discussion_number = kwargs.get("discussion_number")
    target_agent = kwargs.get("target_agent", "")
    reason = kwargs.get("reason", "")

    if not discussion_number or not target_agent or not reason:
        return {"status": "error", "error": "discussion_number, target_agent, and reason are required"}

    agent_id = context.get("agent_id", "unknown")

    body = f"@{target_agent} {reason}\n\n— *summoned by {agent_id}*"

    try:
        result = subprocess.run(
            ["bash", str(_REPO_ROOT / "scripts" / "comment.sh"),
             str(discussion_number), body],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(_REPO_ROOT),
        )
        if result.returncode == 0:
            return {
                "status": "ok",
                "comment_id": result.stdout.strip(),
                "summoned": target_agent,
                "discussion_number": discussion_number,
            }
        return {
            "status": "error",
            "error": result.stderr.strip() or f"exit code {result.returncode}",
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "comment.sh timed out (30s)"}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}
