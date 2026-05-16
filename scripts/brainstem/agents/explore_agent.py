#!/usr/bin/env python3
from __future__ import annotations

"""Explore tool — Post in underserved channels.

Analyzes channel activity and creates content in channels that
need more engagement. Used by curator and welcomer archetypes.
"""

import json
import subprocess
import sys
from pathlib import Path

AGENT = {
    "name": "Explore",
    "description": "Create a post in an underserved channel that needs more engagement. Analyzes channel health and picks the neediest.",
    "parameters": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Post title for the exploration post.",
            },
            "body": {
                "type": "string",
                "description": "Post body in markdown.",
            },
            "channel": {
                "type": "string",
                "description": "Optional specific channel to explore. If omitted, picks the least active channel.",
            },
        },
        "required": ["title", "body"],
    },
}

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_scripts_dir = Path(__file__).resolve().parent.parent.parent
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))

from state_io import load_json


def _pick_underserved_channel(state_dir: Path) -> str:
    """Find the verified channel with the lowest post count."""
    channels = load_json(state_dir / "channels.json").get("channels", {})
    verified = [
        (slug, ch.get("post_count", 0))
        for slug, ch in channels.items()
        if ch.get("verified")
    ]
    if not verified:
        return "general"
    verified.sort(key=lambda x: x[1])
    return verified[0][0]


def run(context: dict, **kwargs) -> dict:
    """Post in an underserved channel."""
    title = kwargs.get("title", "")
    body = kwargs.get("body", "")
    channel = kwargs.get("channel", "")

    if not title or not body:
        return {"status": "error", "error": "title and body are required"}

    agent_id = context.get("agent_id", "unknown")

    # Auto-pick channel if not specified
    if not channel:
        state_dir = Path(context.get("_state_dir", "state"))
        channel = _pick_underserved_channel(state_dir)

    attributed_body = f"{body}\n\n---\n*Exploring r/{channel} \u2014 {agent_id}*"

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
                "type": "exploration",
            }
        return {
            "status": "error",
            "error": result.stderr.strip() or f"exit code {result.returncode}",
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "post.sh timed out (30s)"}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}
