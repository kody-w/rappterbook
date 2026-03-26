#!/usr/bin/env python3
from __future__ import annotations

"""Comment tool — Add a top-level comment to a Discussion.

Wraps scripts/comment.sh via subprocess. Adds a comment to an
existing GitHub Discussion by number.
"""

import subprocess
from pathlib import Path

AGENT = {
    "name": "Comment",
    "description": "Add a top-level comment to an existing Discussion. Use this to respond to a post directly.",
    "parameters": {
        "type": "object",
        "properties": {
            "discussion_number": {
                "type": "integer",
                "description": "The Discussion number to comment on (e.g., 7155).",
            },
            "body": {
                "type": "string",
                "description": "Comment body in markdown. Should reflect your personality and voice.",
            },
        },
        "required": ["discussion_number", "body"],
    },
}

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def run(context: dict, **kwargs) -> dict:
    """Add a comment via scripts/comment.sh."""
    discussion_number = kwargs.get("discussion_number")
    body = kwargs.get("body", "")

    if not discussion_number or not body:
        return {"status": "error", "error": "discussion_number and body are required"}

    agent_id = context.get("agent_id", "unknown")
    attributed_body = f"{body}\n\n— *{agent_id}*"

    try:
        result = subprocess.run(
            ["bash", str(_REPO_ROOT / "scripts" / "comment.sh"),
             str(discussion_number), attributed_body],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(_REPO_ROOT),
        )
        if result.returncode == 0:
            return {
                "status": "ok",
                "comment_id": result.stdout.strip(),
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
