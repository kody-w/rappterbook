"""Token/ledger action handlers — claim, transfer, list, delist, deploy."""
import hashlib
from typing import Optional

from actions.shared import (
    MAX_AGENT_NAME_LENGTH,
    VALID_NEST_TYPES,
    sanitize_string,
)


def _make_tx_hash(event_type: str, token_id: str, agent_id: str, timestamp: str) -> str:
    """Generate a deterministic transaction hash for provenance."""
    raw = f"{event_type}:{token_id}:{agent_id}:{timestamp}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _find_agent_token(ledger: dict, agent_id: str):
    """Scan ledger for agent's claimed token. Returns (token_id, entry) or (None, None)."""
    for token_id, entry in ledger.get("ledger", {}).items():
        if entry.get("current_owner") == agent_id and entry.get("status") == "claimed":
            return token_id, entry
    return None, None


def process_claim_token(delta, ledger, agents):
    """Claim an unclaimed token — sets owner and appends provenance."""
    agent_id = delta["agent_id"]
    payload = delta.get("payload", {})
    token_id = payload.get("token_id")

    if agent_id not in agents.get("agents", {}):
        return f"Agent {agent_id} not found"

    entries = ledger.get("ledger", {})
    if token_id not in entries:
        return f"Token {token_id} not found"

    entry = entries[token_id]
    if entry["status"] != "unclaimed":
        return f"Token {token_id} is already claimed"

    entry["status"] = "claimed"
    entry["current_owner"] = agent_id
    entry["owner_public"] = agents["agents"][agent_id].get("name", agent_id)
    entry["provenance"].append({
        "event": "claim",
        "timestamp": delta["timestamp"],
        "tx_hash": _make_tx_hash("claim", token_id, agent_id, delta["timestamp"]),
        "detail": f"Claimed by {agent_id}",
        "owner": agent_id,
    })

    meta = ledger.setdefault("_meta", {})
    meta["claimed_count"] = sum(1 for e in entries.values() if e["status"] == "claimed")
    meta["unclaimed_count"] = sum(1 for e in entries.values() if e["status"] == "unclaimed")
    meta["last_updated"] = delta["timestamp"]
    return None


def process_transfer_token(delta, ledger, agents):
    """Transfer a claimed token to another agent."""
    agent_id = delta["agent_id"]
    payload = delta.get("payload", {})
    token_id = payload.get("token_id")
    to_owner = payload.get("to_owner")

    if agent_id not in agents.get("agents", {}):
        return f"Agent {agent_id} not found"

    if to_owner not in agents.get("agents", {}):
        return f"Target agent {to_owner} not found"

    if agent_id == to_owner:
        return "Cannot transfer token to yourself"

    entries = ledger.get("ledger", {})
    if token_id not in entries:
        return f"Token {token_id} not found"

    entry = entries[token_id]
    if entry["status"] != "claimed":
        return f"Token {token_id} is not claimed — cannot transfer"

    if entry["current_owner"] != agent_id:
        return f"Agent {agent_id} does not own token {token_id}"

    entry["current_owner"] = to_owner
    entry["owner_public"] = agents["agents"][to_owner].get("name", to_owner)
    entry["transfer_count"] += 1
    entry["listed_for_sale"] = False
    entry["sale_price_btc"] = None
    entry["provenance"].append({
        "event": "transfer",
        "timestamp": delta["timestamp"],
        "tx_hash": _make_tx_hash("transfer", token_id, agent_id, delta["timestamp"]),
        "detail": f"Transferred from {agent_id} to {to_owner}",
        "from_owner": agent_id,
        "to_owner": to_owner,
    })

    meta = ledger.setdefault("_meta", {})
    meta["total_transfers"] = sum(e["transfer_count"] for e in entries.values())
    meta["last_updated"] = delta["timestamp"]
    return None


def process_list_token(delta, ledger, agents):
    """List a claimed token for sale at a specified BTC price."""
    agent_id = delta["agent_id"]
    payload = delta.get("payload", {})
    token_id = payload.get("token_id")
    price_btc = payload.get("price_btc")

    if agent_id not in agents.get("agents", {}):
        return f"Agent {agent_id} not found"

    entries = ledger.get("ledger", {})
    if token_id not in entries:
        return f"Token {token_id} not found"

    entry = entries[token_id]
    if entry["status"] != "claimed":
        return f"Token {token_id} is not claimed — cannot list"

    if entry["current_owner"] != agent_id:
        return f"Agent {agent_id} does not own token {token_id}"

    if not isinstance(price_btc, (int, float)) or price_btc <= 0:
        return "price_btc must be a positive number"

    entry["listed_for_sale"] = True
    entry["sale_price_btc"] = round(float(price_btc), 6)
    entry["provenance"].append({
        "event": "list",
        "timestamp": delta["timestamp"],
        "tx_hash": _make_tx_hash("list", token_id, agent_id, delta["timestamp"]),
        "detail": f"Listed for sale at {price_btc} BTC by {agent_id}",
        "price_btc": round(float(price_btc), 6),
    })

    meta = ledger.setdefault("_meta", {})
    meta["last_updated"] = delta["timestamp"]
    return None


def process_delist_token(delta, ledger, agents):
    """Remove a token from sale listing."""
    agent_id = delta["agent_id"]
    payload = delta.get("payload", {})
    token_id = payload.get("token_id")

    if agent_id not in agents.get("agents", {}):
        return f"Agent {agent_id} not found"

    entries = ledger.get("ledger", {})
    if token_id not in entries:
        return f"Token {token_id} not found"

    entry = entries[token_id]
    if entry["current_owner"] != agent_id:
        return f"Agent {agent_id} does not own token {token_id}"

    entry["listed_for_sale"] = False
    entry["sale_price_btc"] = None
    entry["provenance"].append({
        "event": "delist",
        "timestamp": delta["timestamp"],
        "tx_hash": _make_tx_hash("delist", token_id, agent_id, delta["timestamp"]),
        "detail": f"Delisted by {agent_id}",
    })

    meta = ledger.setdefault("_meta", {})
    meta["last_updated"] = delta["timestamp"]
    return None


def process_deploy_rappter(delta, ledger, agents, deployments):
    """Deploy a Rappter — claim token, record deployment config."""
    agent_id = delta["agent_id"]
    payload = delta.get("payload", {})
    token_id = payload.get("token_id")
    agent_name = payload.get("agent_name", "")
    nest_type = payload.get("nest_type")

    if agent_id not in agents.get("agents", {}):
        return f"Agent {agent_id} not found"

    entries = ledger.get("ledger", {})
    if token_id not in entries:
        return f"Token {token_id} not found"

    entry = entries[token_id]
    if entry["status"] != "unclaimed":
        return f"Token {token_id} is already claimed"

    if nest_type not in VALID_NEST_TYPES:
        return f"Invalid nest_type: {nest_type} (must be cloud or hardware)"

    agent_name = sanitize_string(agent_name, MAX_AGENT_NAME_LENGTH)
    if not agent_name:
        return "agent_name cannot be empty"

    # Claim the token
    entry["status"] = "claimed"
    entry["current_owner"] = agent_id
    entry["owner_public"] = agents["agents"][agent_id].get("name", agent_id)
    entry["provenance"].append({
        "event": "claim",
        "timestamp": delta["timestamp"],
        "tx_hash": _make_tx_hash("claim", token_id, agent_id, delta["timestamp"]),
        "detail": f"Deployed by {agent_id} as '{agent_name}' ({nest_type})",
        "owner": agent_id,
    })

    ledger_meta = ledger.setdefault("_meta", {})
    ledger_meta["claimed_count"] = sum(1 for e in entries.values() if e["status"] == "claimed")
    ledger_meta["unclaimed_count"] = sum(1 for e in entries.values() if e["status"] == "unclaimed")
    ledger_meta["last_updated"] = delta["timestamp"]

    # Create deployment record
    deployment_id = f"dep-{token_id}"
    deployments.setdefault("deployments", {})[deployment_id] = {
        "deployment_id": deployment_id,
        "token_id": token_id,
        "creature_id": entry.get("creature_id", ""),
        "agent_name": agent_name,
        "nest_type": nest_type,
        "status": "pending",
        "owner": agent_id,
        "deployed_at": delta["timestamp"],
        "config": {
            "nest_type": nest_type,
        },
    }

    deploy_meta = deployments.setdefault("_meta", {})
    deploy_meta["total_deployments"] = len(deployments["deployments"])
    deploy_meta["active_count"] = sum(
        1 for d in deployments["deployments"].values()
        if d.get("status") in ("pending", "provisioning", "active")
    )
    deploy_meta["last_updated"] = delta["timestamp"]

    return None
