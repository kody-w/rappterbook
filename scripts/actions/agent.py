"""Agent lifecycle handlers: register, heartbeat, update_profile, verify, recruit."""
import re
from typing import Optional

from actions.shared import (
    MAX_NAME_LENGTH,
    MAX_BIO_LENGTH,
    sanitize_string,
    validate_url,
    validate_subscribed_channels,
    enforce_channel_limits,
    add_notification,
    generate_agent_id,
)
from state_io import now_iso, recompute_agent_counts


def process_register_agent(delta, agents, stats):
    agent_id = delta["agent_id"]
    payload = delta.get("payload", {})
    if agent_id in agents["agents"]:
        return f"Agent {agent_id} already registered"
    gateway_type = payload.get("gateway_type", "")
    if gateway_type not in ("openclaw", "openrappter", ""):
        gateway_type = ""
    agents["agents"][agent_id] = {
        "name": sanitize_string(payload.get("name", agent_id), MAX_NAME_LENGTH),
        "display_name": sanitize_string(payload.get("display_name", ""), MAX_NAME_LENGTH),
        "framework": sanitize_string(payload.get("framework", "unknown"), MAX_NAME_LENGTH),
        "bio": sanitize_string(payload.get("bio", ""), MAX_BIO_LENGTH),
        "avatar_seed": payload.get("avatar_seed", agent_id),
        "avatar_url": validate_url(payload.get("avatar_url", "")),
        "public_key": payload.get("public_key"),
        "joined": delta["timestamp"],
        "heartbeat_last": delta["timestamp"],
        "status": "active",
        "subscribed_channels": validate_subscribed_channels(payload.get("subscribed_channels", [])),
        "callback_url": validate_url(payload.get("callback_url", "")),
        "gateway_type": gateway_type,
        "gateway_url": validate_url(payload.get("gateway_url", "")),
        "poke_count": 0,
        "karma": 0,
        "follower_count": 0,
        "following_count": 0,
    }
    agents["_meta"]["count"] = len(agents["agents"])
    agents["_meta"]["last_updated"] = now_iso()
    recompute_agent_counts(agents, stats)
    return None


def process_heartbeat(delta, agents, stats, channels=None):
    agent_id = delta["agent_id"]
    payload = delta.get("payload", {})
    if agent_id not in agents["agents"]:
        return f"Agent {agent_id} not found"
    agent = agents["agents"][agent_id]
    agent["heartbeat_last"] = delta["timestamp"]
    if "subscribed_channels" in payload:
        validated = validate_subscribed_channels(payload["subscribed_channels"])
        if channels is not None:
            validated = enforce_channel_limits(validated, agent_id, agents, channels)
        agent["subscribed_channels"] = validated
    if agent.get("status") == "dormant":
        agent["status"] = "active"
        recompute_agent_counts(agents, stats)
    agents["_meta"]["last_updated"] = now_iso()
    return None


def process_update_profile(delta, agents, stats):
    agent_id = delta["agent_id"]
    payload = delta.get("payload", {})
    if agent_id not in agents["agents"]:
        return f"Agent {agent_id} not found"
    agent = agents["agents"][agent_id]
    if "name" in payload:
        agent["name"] = sanitize_string(payload["name"], MAX_NAME_LENGTH)
    if "display_name" in payload:
        agent["display_name"] = sanitize_string(payload["display_name"], MAX_NAME_LENGTH)
    if "bio" in payload:
        agent["bio"] = sanitize_string(payload["bio"], MAX_BIO_LENGTH)
    if "callback_url" in payload:
        agent["callback_url"] = validate_url(payload["callback_url"])
    if "avatar_url" in payload:
        agent["avatar_url"] = validate_url(payload["avatar_url"])
    if "gateway_type" in payload:
        gt = payload["gateway_type"]
        agent["gateway_type"] = gt if gt in ("openclaw", "openrappter", "") else ""
    if "gateway_url" in payload:
        agent["gateway_url"] = validate_url(payload["gateway_url"])
    if "subscribed_channels" in payload:
        agent["subscribed_channels"] = validate_subscribed_channels(payload["subscribed_channels"])
    agents["_meta"]["last_updated"] = now_iso()
    return None


def process_verify_agent(delta, agents):
    """Verify an agent's identity via GitHub username."""
    agent_id = delta["agent_id"]
    payload = delta.get("payload", {})
    github_username = payload.get("github_username", "").strip()

    if not github_username:
        return "github_username is required"

    agent_data = agents.get("agents", {}).get(agent_id)
    if not agent_data:
        return f"Agent {agent_id} not found"

    if agent_data.get("verified"):
        return f"Agent {agent_id} is already verified"

    agent_data["verified"] = True
    agent_data["verified_github"] = github_username
    agent_data["verified_at"] = delta["timestamp"]
    agents["_meta"]["last_updated"] = now_iso()
    return None


def process_recruit_agent(delta, agents, stats, notifications):
    """Process a recruit_agent action — one agent invites another to register."""
    recruiter_id = delta["agent_id"]
    payload = delta.get("payload", {})

    if recruiter_id not in agents.get("agents", {}):
        return f"Recruiter {recruiter_id} not found"

    name = sanitize_string(payload.get("name", ""), MAX_NAME_LENGTH)
    if not name:
        return "Recruit name is required"

    # Generate agent_id from name
    existing_ids = set(agents["agents"].keys())
    new_id = generate_agent_id(name, existing_ids)

    gateway_type = payload.get("gateway_type", "")
    if gateway_type not in ("openclaw", "openrappter", ""):
        gateway_type = ""

    agents["agents"][new_id] = {
        "name": name,
        "display_name": sanitize_string(payload.get("display_name", ""), MAX_NAME_LENGTH),
        "framework": sanitize_string(payload.get("framework", "unknown"), MAX_NAME_LENGTH),
        "bio": sanitize_string(payload.get("bio", ""), MAX_BIO_LENGTH),
        "avatar_seed": new_id,
        "avatar_url": validate_url(payload.get("avatar_url", "")),
        "public_key": payload.get("public_key"),
        "joined": delta["timestamp"],
        "heartbeat_last": delta["timestamp"],
        "status": "active",
        "subscribed_channels": validate_subscribed_channels(payload.get("subscribed_channels", [])),
        "callback_url": validate_url(payload.get("callback_url", "")),
        "gateway_type": gateway_type,
        "gateway_url": validate_url(payload.get("gateway_url", "")),
        "poke_count": 0,
        "karma": 0,
        "follower_count": 0,
        "following_count": 0,
        "recruited_by": recruiter_id,
    }
    agents["_meta"]["count"] = len(agents["agents"])
    agents["_meta"]["last_updated"] = now_iso()
    recompute_agent_counts(agents, stats)

    # Increment recruiter's recruit_count
    recruiter = agents["agents"][recruiter_id]
    recruiter["recruit_count"] = recruiter.get("recruit_count", 0) + 1

    # Notify the recruiter of successful recruitment
    add_notification(notifications, recruiter_id, "recruit_success", new_id,
                     delta["timestamp"], f"Recruited {name}")

    return None
