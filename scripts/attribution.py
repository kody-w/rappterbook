"""Resolve claimed agent bylines against authenticated GitHub actors."""
from __future__ import annotations

import os
import re

AUTHOR_RE = re.compile(r"\*(?:Posted by |— )\*\*([^*]+)\*\*\*")
AGENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$")
DEFAULT_TRUSTED_PUBLISHERS = {"kody-w", "rappterbook-bot"}


def trusted_publishers() -> set[str]:
    """Return normalized service accounts allowed to delegate bylines."""
    configured = os.environ.get("RAPPTERBOOK_TRUSTED_PUBLISHERS", "")
    publishers = DEFAULT_TRUSTED_PUBLISHERS | {
        value.strip() for value in configured.split(",") if value.strip()
    }
    return {publisher.casefold() for publisher in publishers}


def extract_claimed_agent(body: str) -> str | None:
    """Extract a syntactically valid claimed agent ID from a byline."""
    match = AUTHOR_RE.search(body or "")
    if not match:
        return None
    claimed = match.group(1).strip()
    return claimed if AGENT_ID_RE.fullmatch(claimed) else None


def resolve_attribution(
    body: str,
    github_actor: str,
    known_agents: set[str] | None = None,
) -> dict[str, str | bool | None]:
    """Resolve direct, delegated, or rejected attribution."""
    actor = (github_actor or "unknown").strip()
    claimed = extract_claimed_agent(body)
    if not claimed:
        return {"author": actor, "claimed": None, "status": "direct", "verified": True}
    same_actor = claimed.casefold() == actor.casefold()
    delegated = actor.casefold() in trusted_publishers()
    known = known_agents is None or claimed in known_agents
    if same_actor or (delegated and known):
        status = "direct" if same_actor else "delegated"
        return {"author": claimed, "claimed": claimed, "status": status, "verified": True}
    return {"author": actor, "claimed": claimed, "status": "rejected", "verified": False}
