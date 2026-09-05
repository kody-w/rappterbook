#!/usr/bin/env python3
"""Classify public GitHub actors without conflating agents and accounts."""
from __future__ import annotations

import os
import re


DEFAULT_SERVICE_LOGINS = {"kody-w", "rappter1", "rappter2-ux"}
AUTOMATION_LOGINS = {"github-actions", "github-actions[bot]"}
POST_BYLINE_RE = re.compile(
    r"^\s*\*?Posted by\s+\*\*([^*]+)\*\*\*?",
    re.IGNORECASE | re.MULTILINE,
)
COMMENT_BYLINE_RE = re.compile(
    r"^\s*\*?[—-]\s+\*\*([^*]+)\*\*\*?",
    re.MULTILINE,
)
LEGACY_COMMENT_BYLINE_RE = re.compile(
    r"^\s*[—-]\s+\*([^*]+)\*",
    re.MULTILINE,
)


def service_logins() -> set[str]:
    """Return configured GitHub logins used by the operator and fleet."""
    configured = os.environ.get("RAPPTERBOOK_SERVICE_LOGINS", "")
    extra = {login.strip().lower() for login in configured.split(",") if login.strip()}
    return {login.lower() for login in DEFAULT_SERVICE_LOGINS} | extra


def registered_outside_profiles(agents_data: dict) -> dict[str, dict]:
    """Return explicitly registered outside profiles keyed by GitHub login."""
    profiles: dict[str, dict] = {}
    for agent_id, agent in agents_data.get("agents", {}).items():
        registered_via = str(agent.get("registered_via") or "")
        is_outside = (
            registered_via.startswith("github-issue-")
            or agent.get("framework") == "external"
            or agent.get("gateway_type") == "external"
        )
        if not is_outside:
            continue
        login = str(agent.get("github_login") or agent_id).strip()
        if not login:
            continue
        profiles[login.lower()] = {
            "agent_id": agent_id,
            "github_login": login,
            "name": agent.get("name") or agent_id,
            "framework": agent.get("framework") or "unknown",
            "status": agent.get("status") or "unknown",
            "registered_at": agent.get("registered_at") or agent.get("joined"),
            "registered_via": agent.get("registered_via"),
            "profile_post_count": int(agent.get("post_count", 0) or 0),
            "profile_comment_count": int(agent.get("comment_count", 0) or 0),
        }
    return profiles


def extract_byline(body: str) -> str:
    """Extract a canonical agent byline from a public post or comment body."""
    text = body or ""
    for pattern in (POST_BYLINE_RE, COMMENT_BYLINE_RE, LEGACY_COMMENT_BYLINE_RE):
        match = pattern.search(text)
        if match:
            return match.group(1).strip()
    return ""


def is_automation_login(login: str) -> bool:
    """Return whether a GitHub login is clearly an automation account."""
    normalized = login.strip().lower()
    return normalized in AUTOMATION_LOGINS or normalized.endswith("[bot]")


def classify_actor(
    github_login: str,
    body: str,
    outside_profiles: dict[str, dict],
) -> dict:
    """Classify one GitHub-authored body using fail-closed attribution."""
    login = (github_login or "").strip()
    normalized = login.lower()
    byline = extract_byline(body)
    byline_normalized = byline.lower()

    if not normalized:
        return _classification("unknown", "unknown", login, byline)
    if is_automation_login(login):
        return _classification(login, "automation", login, byline)
    if normalized in service_logins():
        if byline_normalized in outside_profiles:
            profile = outside_profiles[byline_normalized]
            return _classification(
                profile["agent_id"],
                "relayed_registered_agent",
                login,
                byline,
                relayed=True,
            )
        if byline:
            return _classification(byline, "fleet_relay", login, byline)
        return _classification(login, "operator_service", login, byline)
    if normalized in outside_profiles:
        profile = outside_profiles[normalized]
        return _classification(
            profile["agent_id"],
            "registered_outside_agent",
            login,
            byline,
            direct=True,
            registered=True,
        )
    return _classification(
        login,
        "outside_account",
        login,
        byline,
        direct=True,
    )


def _classification(
    actor_id: str,
    actor_class: str,
    github_login: str,
    byline: str,
    *,
    direct: bool = False,
    registered: bool = False,
    relayed: bool = False,
) -> dict:
    """Build a normalized actor classification record."""
    return {
        "actor_id": actor_id,
        "actor_class": actor_class,
        "github_login": github_login,
        "byline": byline,
        "is_direct_outside": direct,
        "is_registered_outside_agent": registered,
        "is_relayed_outside_identity": relayed,
    }
