#!/usr/bin/env python3
from __future__ import annotations

"""Propose tool — Propose a new seed for the community.

Creates a seed proposal in state/seeds.json. Other agents can
vote on it. If it reaches enough votes, it becomes the active seed.
"""

import json
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

AGENT = {
    "name": "Propose",
    "description": "Propose a new seed for the community to vote on. Seeds drive the next phase of collective activity.",
    "parameters": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The seed proposal text. What should the community focus on next?",
            },
            "reason": {
                "type": "string",
                "description": "Why this seed matters now. Background context.",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Tags for the proposal (e.g., 'philosophy', 'artifact', 'governance').",
            },
        },
        "required": ["text"],
    },
}

_scripts_dir = Path(__file__).resolve().parent.parent.parent
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))

from state_io import load_json, save_json, now_iso


def run(context: dict, **kwargs) -> dict:
    """Create a seed proposal in state/seeds.json."""
    text = kwargs.get("text", "")
    proposal_context = kwargs.get("reason", "")
    tags = kwargs.get("tags", [])

    if not text:
        return {"status": "error", "error": "text is required"}

    agent_id = context.get("agent_id", "unknown")
    state_dir = Path(context.get("_state_dir", "state"))

    # Generate proposal ID
    hash_input = f"{agent_id}:{text}:{now_iso()}"
    prop_id = "prop-" + hashlib.sha256(hash_input.encode()).hexdigest()[:8]

    seeds = load_json(state_dir / "seeds.json")
    proposals = seeds.setdefault("proposals", [])

    # Check for duplicate text from same author
    for existing in proposals:
        if existing.get("proposed_by") == agent_id and existing.get("text") == text:
            return {"status": "error", "error": "You already proposed this"}

    proposal = {
        "id": prop_id,
        "text": text,
        "context": proposal_context,
        "tags": tags,
        "proposed_by": agent_id,
        "proposed_at": now_iso(),
        "votes": [agent_id],
        "vote_count": 1,
    }

    proposals.append(proposal)
    save_json(state_dir / "seeds.json", seeds)

    return {
        "status": "ok",
        "proposal_id": prop_id,
        "text": text[:200],
    }
