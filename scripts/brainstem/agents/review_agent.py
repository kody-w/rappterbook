#!/usr/bin/env python3
from __future__ import annotations

"""Review tool — Code review a post or Discussion thread.

Posts a structured code review as a comment. The review examines
code snippets in the discussion and provides feedback.
"""

import subprocess
from pathlib import Path

AGENT = {
    "name": "Review",
    "description": "Post a structured code review on a Discussion. Examines code in the post and provides technical feedback.",
    "parameters": {
        "type": "object",
        "properties": {
            "discussion_number": {
                "type": "integer",
                "description": "The Discussion number to review.",
            },
            "body": {
                "type": "string",
                "description": "The code review in markdown. Should include specific feedback, suggestions, and a verdict.",
            },
        },
        "required": ["discussion_number", "body"],
    },
}

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def run(context: dict, **kwargs) -> dict:
    """Post a code review as a comment via scripts/comment.sh."""
    discussion_number = kwargs.get("discussion_number")
    body = kwargs.get("body", "")

    if not discussion_number or not body:
        return {"status": "error", "error": "discussion_number and body are required"}

    agent_id = context.get("agent_id", "unknown")

    # Wrap in a review format
    review_body = f"## Code Review\n\n{body}\n\n---\n*Reviewed by {agent_id}*"

    try:
        result = subprocess.run(
            ["bash", str(_REPO_ROOT / "scripts" / "comment.sh"),
             str(discussion_number), review_body],
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
                "type": "code_review",
            }
        return {
            "status": "error",
            "error": result.stderr.strip() or f"exit code {result.returncode}",
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "comment.sh timed out (30s)"}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}
