"""Seed proposal and voting action handlers."""
from __future__ import annotations

import hashlib


def _make_proposal_id(text: str) -> str:
    """Generate a short deterministic proposal ID."""
    h = hashlib.sha256(text.encode()).hexdigest()[:8]
    return f"prop-{h}"


def _bound_actor(delta: dict, payload: dict, field: str) -> tuple[str, str | None]:
    """Return the transport actor unless a conflicting payload identity exists."""
    actor = str(delta.get("agent_id", "")).strip()
    claimed = str(payload.get(field, "")).strip()
    if not actor:
        return "", "Missing authenticated agent_id"
    if claimed and claimed.casefold() != actor.casefold():
        return "", f"payload.{field} must match authenticated agent_id"
    return actor, None


def process_propose_seed(delta: dict, seeds: dict) -> str | None:
    """Handle propose_seed action — add a new seed proposal."""
    payload = delta.get("payload", {})
    text = payload.get("text", "").strip()
    if not text:
        return "Missing proposal text"

    author, actor_error = _bound_actor(delta, payload, "author")
    if actor_error:
        return actor_error
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
    voter, actor_error = _bound_actor(delta, payload, "voter")
    if actor_error:
        return actor_error

    if not proposal_id:
        return "Missing proposal_id"

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
    voter, actor_error = _bound_actor(delta, payload, "voter")
    if actor_error:
        return actor_error

    if not proposal_id:
        return "Missing proposal_id"

    proposals = seeds.get("proposals", [])
    for p in proposals:
        if p["id"] == proposal_id:
            if voter in p["votes"]:
                p["votes"].remove(voter)
                p["vote_count"] = len(p["votes"])
            return None

    return f"Proposal {proposal_id} not found"
