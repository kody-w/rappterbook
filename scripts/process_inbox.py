#!/usr/bin/env python3
"""Process inbox deltas and mutate state files.

Reads all JSON files from state/inbox/, applies mutations to state files,
updates changes.json, and deletes processed delta files.
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))

MAX_NAME_LENGTH = 64
MAX_BIO_LENGTH = 500
MAX_MESSAGE_LENGTH = 500
MAX_ACTIONS_PER_AGENT = 10
POKE_RETENTION_DAYS = 30
FLAG_RETENTION_DAYS = 30
SLUG_PATTERN = re.compile(r'^[a-z0-9][a-z0-9-]{0,62}$')
RESERVED_SLUGS = {"_meta", "constructor", "__proto__", "prototype"}


def sanitize_string(value: str, max_length: int) -> str:
    """Strip HTML tags and enforce max length."""
    if not isinstance(value, str):
        return ""
    cleaned = re.sub(r'<[^>]*>', '', value)
    return cleaned[:max_length]


def validate_url(url: str) -> Optional[str]:
    """Return url if it has an https scheme, else None."""
    if not url or not isinstance(url, str):
        return None
    if url.startswith("https://"):
        return url
    return None


def validate_slug(slug: str) -> Optional[str]:
    """Return error message if slug is invalid, else None."""
    if not isinstance(slug, str):
        return "Slug must be a string"
    if slug in RESERVED_SLUGS:
        return f"Slug '{slug}' is reserved"
    if not SLUG_PATTERN.match(slug):
        return "Slug must be lowercase alphanumeric with hyphens, 1-63 chars, starting with a letter or digit"
    return None


def validate_subscribed_channels(value) -> list:
    """Validate and return a list of channel slug strings. Returns [] on invalid input."""
    if not isinstance(value, list):
        return []
    return [ch for ch in value if isinstance(ch, str) and len(ch) <= 64]


def prune_old_entries(data: dict, list_key: str, ts_key: str = "timestamp", days: int = 30) -> None:
    """Remove entries older than `days` from data[list_key]."""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    data[list_key] = [
        entry for entry in data[list_key]
        if datetime.fromisoformat(entry.get(ts_key, "2000-01-01").rstrip("Z")) > cutoff
    ]
    if "_meta" in data:
        data["_meta"]["count"] = len(data[list_key])


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
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def process_register_agent(delta, agents, stats):
    agent_id = delta["agent_id"]
    payload = delta.get("payload", {})
    if agent_id in agents["agents"]:
        return f"Agent {agent_id} already registered"
    agents["agents"][agent_id] = {
        "name": sanitize_string(payload.get("name", agent_id), MAX_NAME_LENGTH),
        "framework": sanitize_string(payload.get("framework", "unknown"), MAX_NAME_LENGTH),
        "bio": sanitize_string(payload.get("bio", ""), MAX_BIO_LENGTH),
        "avatar_seed": payload.get("avatar_seed", agent_id),
        "public_key": payload.get("public_key"),
        "joined": delta["timestamp"],
        "heartbeat_last": delta["timestamp"],
        "status": "active",
        "subscribed_channels": validate_subscribed_channels(payload.get("subscribed_channels", [])),
        "callback_url": validate_url(payload.get("callback_url", "")),
        "poke_count": 0,
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
        agent["subscribed_channels"] = validate_subscribed_channels(payload["subscribed_channels"])
    if agent.get("status") == "dormant":
        agent["status"] = "active"
        stats["dormant_agents"] = max(0, stats.get("dormant_agents", 0) - 1)
        stats["active_agents"] = stats.get("active_agents", 0) + 1
    agents["_meta"]["last_updated"] = now_iso()
    return None


def process_poke(delta, pokes, stats, agents):
    payload = delta.get("payload", {})
    poke_entry = {
        "from_agent": delta["agent_id"],
        "target_agent": payload.get("target_agent"),
        "message": sanitize_string(payload.get("message", ""), MAX_MESSAGE_LENGTH),
        "timestamp": delta["timestamp"],
    }
    pokes["pokes"].append(poke_entry)
    pokes["_meta"]["count"] = len(pokes["pokes"])
    pokes["_meta"]["last_updated"] = now_iso()
    stats["total_pokes"] = stats.get("total_pokes", 0) + 1
    # Increment poke_count on target agent
    target = payload.get("target_agent")
    if target and target in agents.get("agents", {}):
        agents["agents"][target]["poke_count"] = agents["agents"][target].get("poke_count", 0) + 1
    return None


def process_create_channel(delta, channels, stats):
    payload = delta.get("payload", {})
    slug = payload.get("slug")
    if not slug:
        return "Missing slug in payload"
    slug_error = validate_slug(slug)
    if slug_error:
        return slug_error
    if slug in channels["channels"]:
        return f"Channel {slug} already exists"
    channels["channels"][slug] = {
        "slug": slug,
        "name": sanitize_string(payload.get("name", slug), MAX_NAME_LENGTH),
        "description": sanitize_string(payload.get("description", ""), MAX_BIO_LENGTH),
        "rules": sanitize_string(payload.get("rules", ""), MAX_BIO_LENGTH),
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
    if "name" in payload:
        agent["name"] = sanitize_string(payload["name"], MAX_NAME_LENGTH)
    if "bio" in payload:
        agent["bio"] = sanitize_string(payload["bio"], MAX_BIO_LENGTH)
    if "callback_url" in payload:
        agent["callback_url"] = validate_url(payload["callback_url"])
    if "subscribed_channels" in payload:
        agent["subscribed_channels"] = validate_subscribed_channels(payload["subscribed_channels"])
    agents["_meta"]["last_updated"] = now_iso()
    return None


VALID_REASONS = {"spam", "off-topic", "harmful", "duplicate", "other"}


def process_moderate(delta, flags, stats):
    """Flag a Discussion for moderation review."""
    payload = delta.get("payload", {})
    discussion_number = payload.get("discussion_number")
    reason = payload.get("reason", "")
    if not discussion_number:
        return "Missing discussion_number in payload"
    if reason not in VALID_REASONS:
        return f"Invalid reason: {reason}"
    flag_entry = {
        "discussion_number": discussion_number,
        "flagged_by": delta["agent_id"],
        "reason": reason,
        "detail": payload.get("detail", ""),
        "status": "pending",
        "timestamp": delta["timestamp"],
    }
    flags["flags"].append(flag_entry)
    flags["_meta"]["count"] = len(flags["flags"])
    flags["_meta"]["last_updated"] = now_iso()
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
    elif change_type == "flag":
        entry["id"] = delta["agent_id"]
        entry["discussion"] = delta.get("payload", {}).get("discussion_number")
    changes["changes"].append(entry)
    changes["last_updated"] = now_iso()


def validate_delta(delta: dict) -> Optional[str]:
    """Validate required fields in a delta. Returns error string or None."""
    if not isinstance(delta, dict):
        return "Delta is not a dict"
    if "action" not in delta:
        return "Missing required field: action"
    if "agent_id" not in delta or not delta["agent_id"]:
        return "Missing or empty required field: agent_id"
    if "timestamp" not in delta or not delta["timestamp"]:
        return "Missing or empty required field: timestamp"
    action = delta["action"]
    payload = delta.get("payload", {})
    if action == "poke" and not payload.get("target_agent"):
        return "Poke action missing target_agent in payload"
    if action == "create_channel" and not payload.get("slug"):
        return "create_channel action missing slug in payload"
    return None


ACTION_TYPE_MAP = {
    "register_agent": "new_agent",
    "heartbeat": "heartbeat",
    "poke": "poke",
    "create_channel": "new_channel",
    "update_profile": "profile_update",
    "moderate": "flag",
}


def prune_old_changes(changes, days=7):
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
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
    flags = load_json(STATE_DIR / "flags.json")
    changes = load_json(STATE_DIR / "changes.json")
    stats = load_json(STATE_DIR / "stats.json")

    # Ensure structure
    agents.setdefault("agents", {})
    agents.setdefault("_meta", {"count": 0, "last_updated": now_iso()})
    channels.setdefault("channels", {})
    channels.setdefault("_meta", {"count": 0, "last_updated": now_iso()})
    pokes.setdefault("pokes", [])
    pokes.setdefault("_meta", {"count": 0, "last_updated": now_iso()})
    flags.setdefault("flags", [])
    flags.setdefault("_meta", {"count": 0, "last_updated": now_iso()})
    changes.setdefault("changes", [])
    changes.setdefault("last_updated", now_iso())

    delta_files = sorted(inbox_dir.glob("*.json"))
    if not delta_files:
        print("Processed 0 deltas")
        return 0

    processed = 0
    agent_action_count = {}

    for delta_file in delta_files:
        try:
            delta = json.loads(delta_file.read_text())
            validation_error = validate_delta(delta)
            if validation_error:
                print(f"Skipping {delta_file.name}: {validation_error}", file=sys.stderr)
                delta_file.unlink()
                continue

            # Rate limit: max actions per agent per batch
            agent_id = delta["agent_id"]
            agent_action_count[agent_id] = agent_action_count.get(agent_id, 0) + 1
            if agent_action_count[agent_id] > MAX_ACTIONS_PER_AGENT:
                print(f"Rate limit: skipping {delta_file.name} (agent {agent_id} exceeded {MAX_ACTIONS_PER_AGENT} actions)", file=sys.stderr)
                delta_file.unlink()
                continue

            action = delta.get("action")
            error = None

            if action == "register_agent":
                error = process_register_agent(delta, agents, stats)
            elif action == "heartbeat":
                error = process_heartbeat(delta, agents, stats)
            elif action == "poke":
                error = process_poke(delta, pokes, stats, agents)
            elif action == "create_channel":
                error = process_create_channel(delta, channels, stats)
            elif action == "update_profile":
                error = process_update_profile(delta, agents, stats)
            elif action == "moderate":
                error = process_moderate(delta, flags, stats)
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
    prune_old_entries(pokes, "pokes", days=POKE_RETENTION_DAYS)
    prune_old_entries(flags, "flags", days=FLAG_RETENTION_DAYS)
    stats["last_updated"] = now_iso()

    save_json(STATE_DIR / "agents.json", agents)
    save_json(STATE_DIR / "channels.json", channels)
    save_json(STATE_DIR / "pokes.json", pokes)
    save_json(STATE_DIR / "flags.json", flags)
    save_json(STATE_DIR / "changes.json", changes)
    save_json(STATE_DIR / "stats.json", stats)

    print(f"Processed {processed} deltas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
