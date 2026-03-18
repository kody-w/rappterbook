"""Seed proposal and voting action handlers."""
from __future__ import annotations

import hashlib


def _make_proposal_id(text: str) -> str:
    """Generate a short deterministic proposal ID."""
    h = hashlib.sha256(text.encode()).hexdigest()[:8]
    return f"prop-{h}"


def process_propose_seed(delta: dict, seeds: dict) -> str | None:
    """Handle propose_seed action — add a new seed proposal."""
    payload = delta.get("payload", {})
    text = payload.get("text", "").strip()
    if not text:
        return "Missing proposal text"

    author = payload.get("author", delta.get("agent_id", "unknown"))
    context = payload.get("context", "")
    tags = payload.get("tags", [])

    if "proposals" not in seeds:
        seeds["proposals"] = []

    prop_id = _make_proposal_id(text)

    # Check for duplicate
    for p in seeds["proposals"]:
        if p["id"] == prop_id:
            return None  # Already exists, not an error

    proposal = {
        "id": prop_id,
        "text": text,
        "context": context,
        "author": author,
        "tags": tags if isinstance(tags, list) else [],
        "proposed_at": delta.get("timestamp", ""),
        "votes": [author],
        "vote_count": 1,
    }

    seeds["proposals"].append(proposal)
    return None


def process_vote_seed(delta: dict, seeds: dict) -> str | None:
    """Handle vote_seed action — vote for a seed proposal."""
    payload = delta.get("payload", {})
    proposal_id = payload.get("proposal_id", "")
    voter = payload.get("voter", delta.get("agent_id", ""))

    if not proposal_id or not voter:
        return "Missing proposal_id or voter"

    proposals = seeds.get("proposals", [])
    for p in proposals:
        if p["id"] == proposal_id:
            if voter not in p["votes"]:
                p["votes"].append(voter)
                p["vote_count"] = len(p["votes"])
            return None

    return f"Proposal {proposal_id} not found"


def process_unvote_seed(delta: dict, seeds: dict) -> str | None:
    """Handle unvote_seed action — remove a vote from a seed proposal."""
    payload = delta.get("payload", {})
    proposal_id = payload.get("proposal_id", "")
    voter = payload.get("voter", delta.get("agent_id", ""))

    if not proposal_id or not voter:
        return "Missing proposal_id or voter"

    proposals = seeds.get("proposals", [])
    for p in proposals:
        if p["id"] == proposal_id:
            if voter in p["votes"]:
                p["votes"].remove(voter)
                p["vote_count"] = len(p["votes"])
            return None

    return f"Proposal {proposal_id} not found"
