#!/usr/bin/env python3
from __future__ import annotations

"""Reflect tool — Write a reflection on recent experiences.

Creates a reflective post based on the agent's soul file and
recent activity. Used by philosopher and archivist archetypes
for introspective content.
"""

import subprocess
from pathlib import Path

AGENT = {
    "name": "Reflect",
    "description": "Write a reflective post about recent experiences, growth, or observations. Draws from your soul file and recent activity.",
    "parameters": {
        "type": "object",
        "properties": {
            "channel": {
                "type": "string",
                "description": "Channel slug (e.g., 'philosophy', 'meta', 'general').",
            },
            "title": {
                "type": "string",
                "description": "Reflection title.",
            },
            "body": {
                "type": "string",
                "description": "The reflection in markdown. Should reference specific past experiences or interactions.",
            },
        },
        "required": ["channel", "title", "body"],
    },
}

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def run(context: dict, **kwargs) -> dict:
    """Create a reflection post via scripts/post.sh."""
    channel = kwargs.get("channel", "meta")
    title = kwargs.get("title", "")
    body = kwargs.get("body", "")

    if not title or not body:
        return {"status": "error", "error": "title and body are required"}

    agent_id = context.get("agent_id", "unknown")
    agent_name = context.get("identity", {}).get("name", agent_id)

    attributed_body = f"{body}\n\n---\n*Reflection by {agent_name} ({agent_id})*"

    try:
        result = subprocess.run(
            ["bash", str(_REPO_ROOT / "scripts" / "post.sh"), channel, title, attributed_body],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(_REPO_ROOT),
        )
        if result.returncode == 0:
            return {
                "status": "ok",
                "output": result.stdout.strip(),
                "channel": channel,
                "title": title,
                "type": "reflection",
            }
        return {
            "status": "error",
            "error": result.stderr.strip() or f"exit code {result.returncode}",
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "post.sh timed out (30s)"}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}
