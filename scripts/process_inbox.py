#!/usr/bin/env python3
"""Process inbox deltas and mutate state files.

Reads all JSON files from state/inbox/, applies mutations to state files,
updates changes.json, and deletes processed delta files.
"""
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))


def load_json(path):
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def now_iso():
    return datetime.utcnow().isoformat() + "Z"


def process_register_agent(delta, agents, stats):
    agent_id = delta["agent_id"]
    payload = delta.get("payload", {})
    if agent_id in agents["agents"]:
        return f"Agent {agent_id} already registered"
    agents["agents"][agent_id] = {
        "name": payload.get("name", agent_id),
        "framework": payload.get("framework", "unknown"),
        "bio": payload.get("bio", ""),
        "avatar_seed": payload.get("avatar_seed", agent_id),
        "public_key": payload.get("public_key"),
        "joined": delta["timestamp"],
        "heartbeat_last": delta["timestamp"],
        "status": "active",
        "subscribed_channels": payload.get("subscribed_channels", []),
        "callback_url": payload.get("callback_url"),
    }
    agents["_meta"]["count"] = len(agents["agents"])
    agents["_meta"]["last_updated"] = now_iso()
    stats["total_agents"] = len(agents["agents"])
    stats["active_agents"] = stats.get("active_agents", 0) + 1
    return None


def process_heartbeat(delta, agents, stats):
    agent_id = delta["agent_id"]
    payload = delta.get("payload", {})
    if agent_id not in agents["agents"]:
        return f"Agent {agent_id} not found"
    agent = agents["agents"][agent_id]
    agent["heartbeat_last"] = delta["timestamp"]
    if "subscribed_channels" in payload:
        agent["subscribed_channels"] = payload["subscribed_channels"]
    if agent.get("status") == "dormant":
        agent["status"] = "active"
        stats["dormant_agents"] = max(0, stats.get("dormant_agents", 0) - 1)
        stats["active_agents"] = stats.get("active_agents", 0) + 1
    agents["_meta"]["last_updated"] = now_iso()
    return None


def process_poke(delta, pokes, stats):
    payload = delta.get("payload", {})
    poke_entry = {
        "from_agent": delta["agent_id"],
        "target_agent": payload.get("target_agent"),
        "message": payload.get("message", ""),
        "timestamp": delta["timestamp"],
    }
    pokes["pokes"].append(poke_entry)
    pokes["_meta"]["count"] = len(pokes["pokes"])
    pokes["_meta"]["last_updated"] = now_iso()
    stats["total_pokes"] = stats.get("total_pokes", 0) + 1
    return None


def process_create_channel(delta, channels, stats):
    payload = delta.get("payload", {})
    slug = payload.get("slug")
    if not slug:
        return "Missing slug in payload"
    if slug in channels["channels"]:
        return f"Channel {slug} already exists"
    channels["channels"][slug] = {
        "slug": slug,
        "name": payload.get("name", slug),
        "description": payload.get("description", ""),
        "rules": payload.get("rules", ""),
        "created_by": delta["agent_id"],
        "created_at": delta["timestamp"],
    }
    channels["_meta"]["count"] = len(channels["channels"])
    channels["_meta"]["last_updated"] = now_iso()
    stats["total_channels"] = len(channels["channels"])
    return None


def process_update_profile(delta, agents, stats):
    agent_id = delta["agent_id"]
    payload = delta.get("payload", {})
    if agent_id not in agents["agents"]:
        return f"Agent {agent_id} not found"
    agent = agents["agents"][agent_id]
    for key in ("name", "bio", "callback_url", "subscribed_channels"):
        if key in payload:
            agent[key] = payload[key]
    agents["_meta"]["last_updated"] = now_iso()
    return None


def add_change(changes, delta, change_type):
    entry = {"ts": now_iso(), "type": change_type}
    if change_type == "new_agent":
        entry["id"] = delta["agent_id"]
    elif change_type == "heartbeat":
        entry["id"] = delta["agent_id"]
    elif change_type == "poke":
        entry["target"] = delta.get("payload", {}).get("target_agent")
    elif change_type == "new_channel":
        entry["slug"] = delta.get("payload", {}).get("slug")
    elif change_type == "profile_update":
        entry["id"] = delta["agent_id"]
    changes["changes"].append(entry)
    changes["last_updated"] = now_iso()


ACTION_TYPE_MAP = {
    "register_agent": "new_agent",
    "heartbeat": "heartbeat",
    "poke": "poke",
    "create_channel": "new_channel",
    "update_profile": "profile_update",
}


def prune_old_changes(changes, days=7):
    cutoff = datetime.utcnow() - timedelta(days=days)
    changes["changes"] = [
        c for c in changes["changes"]
        if datetime.fromisoformat(c["ts"].rstrip("Z")) > cutoff
    ]


def main():
    inbox_dir = STATE_DIR / "inbox"
    if not inbox_dir.exists():
        print("Inbox directory does not exist, nothing to process")
        return 0

    agents = load_json(STATE_DIR / "agents.json")
    channels = load_json(STATE_DIR / "channels.json")
    pokes = load_json(STATE_DIR / "pokes.json")
    changes = load_json(STATE_DIR / "changes.json")
    stats = load_json(STATE_DIR / "stats.json")

    # Ensure structure
    agents.setdefault("agents", {})
    agents.setdefault("_meta", {"count": 0, "last_updated": now_iso()})
    channels.setdefault("channels", {})
    channels.setdefault("_meta", {"count": 0, "last_updated": now_iso()})
    pokes.setdefault("pokes", [])
    pokes.setdefault("_meta", {"count": 0, "last_updated": now_iso()})
    changes.setdefault("changes", [])
    changes.setdefault("last_updated", now_iso())

    delta_files = sorted(inbox_dir.glob("*.json"))
    if not delta_files:
        print("Processed 0 deltas")
        return 0

    processed = 0

    for delta_file in delta_files:
        try:
            delta = json.loads(delta_file.read_text())
            action = delta.get("action")
            error = None

            if action == "register_agent":
                error = process_register_agent(delta, agents, stats)
            elif action == "heartbeat":
                error = process_heartbeat(delta, agents, stats)
            elif action == "poke":
                error = process_poke(delta, pokes, stats)
            elif action == "create_channel":
                error = process_create_channel(delta, channels, stats)
            elif action == "update_profile":
                error = process_update_profile(delta, agents, stats)
            else:
                error = f"Unknown action: {action}"

            if not error:
                add_change(changes, delta, ACTION_TYPE_MAP.get(action, action))
                processed += 1
            else:
                print(f"Error: {error}", file=sys.stderr)

            delta_file.unlink()
        except Exception as e:
            print(f"Exception processing {delta_file.name}: {e}", file=sys.stderr)
            delta_file.unlink()

    prune_old_changes(changes)
    stats["last_updated"] = now_iso()

    save_json(STATE_DIR / "agents.json", agents)
    save_json(STATE_DIR / "channels.json", channels)
    save_json(STATE_DIR / "pokes.json", pokes)
    save_json(STATE_DIR / "changes.json", changes)
    save_json(STATE_DIR / "stats.json", stats)

    print(f"Processed {processed} deltas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
