#!/usr/bin/env python3
from __future__ import annotations

"""Reply tool — Reply to a specific comment in a Discussion.

Wraps scripts/reply.sh which handles depth automatically:
  - Replying to a top-level comment -> direct reply
  - Replying to a nested reply -> thread marker + root reply
"""

import subprocess
from pathlib import Path

AGENT = {
    "name": "Reply",
    "description": "Reply to a specific comment in a Discussion thread. Handles threading depth automatically.",
    "parameters": {
        "type": "object",
        "properties": {
            "discussion_number": {
                "type": "integer",
                "description": "The Discussion number containing the comment.",
            },
            "comment_id": {
                "type": "string",
                "description": "The node ID of the comment to reply to (e.g., 'DC_kwDORPJAUs4A924-').",
            },
            "body": {
                "type": "string",
                "description": "Reply body in markdown.",
            },
        },
        "required": ["discussion_number", "comment_id", "body"],
    },
}

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def run(context: dict, **kwargs) -> dict:
    """Reply to a comment via scripts/reply.sh."""
    discussion_number = kwargs.get("discussion_number")
    comment_id = kwargs.get("comment_id", "")
    body = kwargs.get("body", "")

    if not discussion_number or not comment_id or not body:
        return {"status": "error", "error": "discussion_number, comment_id, and body are required"}

    agent_id = context.get("agent_id", "unknown")
    attributed_body = f"{body}\n\n— *{agent_id}*"

    try:
        result = subprocess.run(
            ["bash", str(_REPO_ROOT / "scripts" / "reply.sh"),
             str(discussion_number), comment_id, attributed_body],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(_REPO_ROOT),
        )
        if result.returncode == 0:
            return {
                "status": "ok",
                "reply_id": result.stdout.strip(),
                "discussion_number": discussion_number,
                "in_reply_to": comment_id,
            }
        return {
            "status": "error",
            "error": result.stderr.strip() or f"exit code {result.returncode}",
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "reply.sh timed out (30s)"}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}
