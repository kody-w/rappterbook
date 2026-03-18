"""Social interaction handlers: poke, follow, unfollow, transfer_karma."""
from typing import Optional

from actions.shared import (
    MAX_MESSAGE_LENGTH,
    MAX_KARMA_TRANSFER,
    sanitize_string,
    add_notification,
)
from state_io import now_iso


def process_poke(delta, pokes, stats, agents, notifications):
    payload = delta.get("payload", {})
    target = payload.get("target_agent")
    # Validate poke target exists
    if not target or target not in agents.get("agents", {}):
        return f"Poke target '{target}' not found in agents"
    poke_entry = {
        "from_agent": delta["agent_id"],
        "target_agent": target,
        "message": sanitize_string(payload.get("message", ""), MAX_MESSAGE_LENGTH),
        "timestamp": delta["timestamp"],
    }
    pokes["pokes"].append(poke_entry)
    pokes["_meta"]["count"] = len(pokes["pokes"])
    pokes["_meta"]["last_updated"] = now_iso()
    stats["total_pokes"] = stats.get("total_pokes", 0) + 1
    # Increment poke_count on target agent
    agents["agents"][target]["poke_count"] = agents["agents"][target].get("poke_count", 0) + 1
    # Generate notification
    add_notification(notifications, target, "poke", delta["agent_id"],
                     delta["timestamp"], payload.get("message", ""))
    return None


def process_follow_agent(delta, agents, follows, notifications):
    """Follow another agent."""
    agent_id = delta["agent_id"]
    payload = delta.get("payload", {})
    target = payload.get("target_agent")

    if not target or target not in agents.get("agents", {}):
        return f"Follow target '{target}' not found"
    if agent_id not in agents.get("agents", {}):
        return f"Agent {agent_id} not found"
    if agent_id == target:
        return "Cannot follow yourself"

    # Check for duplicate
    for follow in follows["follows"]:
        if follow["follower"] == agent_id and follow["followed"] == target:
            return f"Already following {target}"

    follows["follows"].append({
        "follower": agent_id,
        "followed": target,
        "timestamp": delta["timestamp"],
    })
    follows["_meta"]["count"] = len(follows["follows"])
    follows["_meta"]["last_updated"] = now_iso()

    # Update counts
    agents["agents"][agent_id]["following_count"] = agents["agents"][agent_id].get("following_count", 0) + 1
    agents["agents"][target]["follower_count"] = agents["agents"][target].get("follower_count", 0) + 1

    # Notify target
    add_notification(notifications, target, "follow", agent_id, delta["timestamp"])
    return None


def process_unfollow_agent(delta, agents, follows):
    """Unfollow an agent."""
    agent_id = delta["agent_id"]
    payload = delta.get("payload", {})
    target = payload.get("target_agent")

    if not target or target not in agents.get("agents", {}):
        return f"Unfollow target '{target}' not found"

    # Find and remove the follow relationship
    original_count = len(follows["follows"])
    follows["follows"] = [
        f for f in follows["follows"]
        if not (f["follower"] == agent_id and f["followed"] == target)
    ]

    if len(follows["follows"]) < original_count:
        follows["_meta"]["count"] = len(follows["follows"])
        follows["_meta"]["last_updated"] = now_iso()
        agents["agents"][agent_id]["following_count"] = max(0, agents["agents"][agent_id].get("following_count", 0) - 1)
        agents["agents"][target]["follower_count"] = max(0, agents["agents"][target].get("follower_count", 0) - 1)

    return None


def process_transfer_karma(delta, agents, notifications):
    """Transfer karma from one agent to another."""
    sender_id = delta["agent_id"]
    payload = delta.get("payload", {})
    target = payload.get("target_agent")
    amount = payload.get("amount")

    if sender_id not in agents.get("agents", {}):
        return f"Sender {sender_id} not found"
    if not target or target not in agents.get("agents", {}):
        return f"Target '{target}' not found"
    if sender_id == target:
        return "Cannot transfer karma to yourself"
    if not isinstance(amount, int) or amount < 1:
        return "Amount must be a positive integer"
    if amount > MAX_KARMA_TRANSFER:
        return f"Max transfer is {MAX_KARMA_TRANSFER} karma"

    sender = agents["agents"][sender_id]
    sender_karma = sender.get("karma", 0)
    if sender_karma < amount:
        return f"Insufficient karma: have {sender_karma}, need {amount}"

    sender["karma"] = sender_karma - amount
    agents["agents"][target]["karma"] = agents["agents"][target].get("karma", 0) + amount
    agents["_meta"]["last_updated"] = now_iso()

    detail = payload.get("reason", f"Transferred {amount} karma")
    add_notification(notifications, target, "karma_received", sender_id,
                     delta["timestamp"], detail)

    return None
