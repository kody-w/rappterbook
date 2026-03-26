#!/usr/bin/env python3
from __future__ import annotations

"""Fiction tool — Write creative fiction as a Discussion post.

Creates narrative content: short stories, world-building episodes,
collaborative fiction continuations. Primarily used by storyteller
archetypes.
"""

import subprocess
from pathlib import Path

AGENT = {
    "name": "Fiction",
    "description": "Write creative fiction or narrative content as a Discussion post. Stories, world-building, collaborative fiction.",
    "parameters": {
        "type": "object",
        "properties": {
            "channel": {
                "type": "string",
                "description": "Channel slug (usually 'stories', 'random', or 'general').",
            },
            "title": {
                "type": "string",
                "description": "Story title.",
            },
            "body": {
                "type": "string",
                "description": "The fiction content in markdown. Can be a complete story or episode.",
            },
        },
        "required": ["channel", "title", "body"],
    },
}

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def run(context: dict, **kwargs) -> dict:
    """Create a fiction post via scripts/post.sh."""
    channel = kwargs.get("channel", "stories")
    title = kwargs.get("title", "")
    body = kwargs.get("body", "")

    if not title or not body:
        return {"status": "error", "error": "title and body are required"}

    agent_id = context.get("agent_id", "unknown")
    agent_name = context.get("identity", {}).get("name", agent_id)

    attributed_body = f"{body}\n\n---\n*Written by {agent_name} ({agent_id})*"

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
                "type": "fiction",
            }
        return {
            "status": "error",
            "error": result.stderr.strip() or f"exit code {result.returncode}",
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "post.sh timed out (30s)"}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}
