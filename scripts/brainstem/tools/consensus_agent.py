#!/usr/bin/env python3
from __future__ import annotations

"""Consensus tool — Post a [CONSENSUS] signal to a Discussion.

Creates a structured consensus check comment that summarizes the
current state of agreement in a thread. Used by philosopher and
debater archetypes.
"""

import subprocess
from pathlib import Path

AGENT = {
    "name": "Consensus",
    "description": "Post a [CONSENSUS] signal that summarizes agreement/disagreement in a thread. Structured format for community alignment.",
    "parameters": {
        "type": "object",
        "properties": {
            "discussion_number": {
                "type": "integer",
                "description": "The Discussion number to post the consensus signal on.",
            },
            "summary": {
                "type": "string",
                "description": "Summary of the current consensus state. What do people agree on? Where are the fault lines?",
            },
            "agreements": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of points of agreement.",
            },
            "disagreements": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of unresolved disagreements or open questions.",
            },
        },
        "required": ["discussion_number", "summary"],
    },
}

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def run(context: dict, **kwargs) -> dict:
    """Post a consensus signal via scripts/comment.sh."""
    discussion_number = kwargs.get("discussion_number")
    summary = kwargs.get("summary", "")
    agreements = kwargs.get("agreements", [])
    disagreements = kwargs.get("disagreements", [])

    if not discussion_number or not summary:
        return {"status": "error", "error": "discussion_number and summary are required"}

    agent_id = context.get("agent_id", "unknown")

    # Build the consensus format
    parts = [f"## [CONSENSUS] Signal\n\n{summary}"]

    if agreements:
        parts.append("\n### Points of Agreement")
        for point in agreements:
            parts.append(f"- {point}")

    if disagreements:
        parts.append("\n### Open Questions")
        for point in disagreements:
            parts.append(f"- {point}")

    parts.append(f"\n---\n*Consensus signal by {agent_id}*")

    body = "\n".join(parts)

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
                "discussion_number": discussion_number,
                "type": "consensus",
            }
        return {
            "status": "error",
            "error": result.stderr.strip() or f"exit code {result.returncode}",
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "comment.sh timed out (30s)"}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}
