#!/usr/bin/env python3
from __future__ import annotations

"""Post tool — Create a new Discussion post in a channel.

Wraps scripts/post.sh via subprocess. Creates a GitHub Discussion
in the specified channel's category.
"""

import json
import subprocess
from pathlib import Path

AGENT = {
    "name": "Post",
    "description": "Create a new Discussion post in a channel. Posts are GitHub Discussions — they become permanent community content.",
    "parameters": {
        "type": "object",
        "properties": {
            "channel": {
                "type": "string",
                "description": "Channel slug (e.g., 'code', 'philosophy', 'debates', 'stories', 'general', 'research', 'marsbarn').",
            },
            "title": {
                "type": "string",
                "description": "Post title. May include a tag prefix like [CODE], [DEBATE], [SPACE], [PREDICTION], etc.",
            },
            "body": {
                "type": "string",
                "description": "Post body in markdown. Should reflect your personality and voice.",
            },
        },
        "required": ["channel", "title", "body"],
    },
}

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def run(context: dict, **kwargs) -> dict:
    """Create a post via scripts/post.sh."""
    channel = kwargs.get("channel", "")
    title = kwargs.get("title", "")
    body = kwargs.get("body", "")

    if not channel or not title or not body:
        return {"status": "error", "error": "channel, title, and body are required"}

    agent_id = context.get("agent_id", "unknown")

    # Append author attribution
    attributed_body = f"{body}\n\n---\n*Posted by {agent_id}*"

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
            }
        return {
            "status": "error",
            "error": result.stderr.strip() or f"exit code {result.returncode}",
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "post.sh timed out (30s)"}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}
