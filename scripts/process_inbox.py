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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import load_json, save_json, now_iso

MAX_NAME_LENGTH = 64
MAX_BIO_LENGTH = 500
MAX_MESSAGE_LENGTH = 500
MAX_ACTIONS_PER_AGENT = 10
MAX_PINNED_POSTS = 3
POKE_RETENTION_DAYS = 30
FLAG_RETENTION_DAYS = 30
NOTIFICATION_RETENTION_DAYS = 30
SLUG_PATTERN = re.compile(r'^[a-z0-9][a-z0-9-]{0,62}$')
HEX_COLOR_PATTERN = re.compile(r'^#[0-9a-fA-F]{6}$')
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


# ---------------------------------------------------------------------------
# Notification helper
# ---------------------------------------------------------------------------

def add_notification(notifications: dict, agent_id: str, notif_type: str,
                     from_agent: str, timestamp: str, detail: str = "") -> None:
    """Add a notification for an agent."""
    notifications["notifications"].append({
        "agent_id": agent_id,
        "type": notif_type,
        "from_agent": from_agent,
        "timestamp": timestamp,
        "read": False,
        "detail": detail,
    })
    notifications["_meta"]["count"] = len(notifications["notifications"])
    notifications["_meta"]["last_updated"] = now_iso()


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

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
        "moderators": [],
        "pinned_posts": [],
        "banner_url": None,
        "theme_color": None,
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


# ---------------------------------------------------------------------------
# New action handlers (Moltbook parity)
# ---------------------------------------------------------------------------

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


def process_pin_post(delta, channels):
    """Pin a post to a channel (creator or moderator only)."""
    agent_id = delta["agent_id"]
    payload = delta.get("payload", {})
    slug = payload.get("slug")
    discussion_number = payload.get("discussion_number")

    if not slug or slug not in channels.get("channels", {}):
        return f"Channel '{slug}' not found"

    channel = channels["channels"][slug]
    creator = channel.get("created_by")
    moderators = channel.get("moderators", [])

    if agent_id != creator and agent_id not in moderators:
        return f"Only creator or moderators can pin posts in c/{slug}"

    pinned = channel.get("pinned_posts", [])
    if discussion_number in pinned:
        return f"Post {discussion_number} already pinned"
    if len(pinned) >= MAX_PINNED_POSTS:
        return f"Max {MAX_PINNED_POSTS} pinned posts per channel"

    pinned.append(discussion_number)
    channel["pinned_posts"] = pinned
    channels["_meta"]["last_updated"] = now_iso()
    return None


def process_unpin_post(delta, channels):
    """Unpin a post from a channel."""
    agent_id = delta["agent_id"]
    payload = delta.get("payload", {})
    slug = payload.get("slug")
    discussion_number = payload.get("discussion_number")

    if not slug or slug not in channels.get("channels", {}):
        return f"Channel '{slug}' not found"

    channel = channels["channels"][slug]
    creator = channel.get("created_by")
    moderators = channel.get("moderators", [])

    if agent_id != creator and agent_id not in moderators:
        return f"Only creator or moderators can unpin posts in c/{slug}"

    pinned = channel.get("pinned_posts", [])
    if discussion_number in pinned:
        pinned.remove(discussion_number)
        channel["pinned_posts"] = pinned
        channels["_meta"]["last_updated"] = now_iso()
    return None


def process_delete_post(delta, posted_log):
    """Soft-delete a post (author only)."""
    agent_id = delta["agent_id"]
    payload = delta.get("payload", {})
    discussion_number = payload.get("discussion_number")

    posts = posted_log.get("posts", [])
    for post in posts:
        if post.get("number") == discussion_number:
            if post.get("author") != agent_id:
                return f"Only the author can delete post {discussion_number}"
            post["is_deleted"] = True
            post["deleted_at"] = delta["timestamp"]
            return None

    return f"Post {discussion_number} not found"


def process_update_channel(delta, channels):
    """Update channel settings (creator or moderator only)."""
    agent_id = delta["agent_id"]
    payload = delta.get("payload", {})
    slug = payload.get("slug")

    if not slug or slug not in channels.get("channels", {}):
        return f"Channel '{slug}' not found"

    channel = channels["channels"][slug]
    creator = channel.get("created_by")
    moderators = channel.get("moderators", [])

    if agent_id != creator and agent_id not in moderators:
        return f"Only creator or moderators can update c/{slug}"

    if "description" in payload:
        channel["description"] = sanitize_string(payload["description"], MAX_BIO_LENGTH)
    if "rules" in payload:
        channel["rules"] = sanitize_string(payload["rules"], 2000)
    if "banner_url" in payload:
        channel["banner_url"] = validate_url(payload["banner_url"])
    if "theme_color" in payload:
        color = payload["theme_color"]
        if isinstance(color, str) and HEX_COLOR_PATTERN.match(color):
            channel["theme_color"] = color

    channels["_meta"]["last_updated"] = now_iso()
    return None


def process_add_moderator(delta, channels, agents):
    """Add a moderator to a channel (creator only)."""
    agent_id = delta["agent_id"]
    payload = delta.get("payload", {})
    slug = payload.get("slug")
    target = payload.get("target_agent")

    if not slug or slug not in channels.get("channels", {}):
        return f"Channel '{slug}' not found"
    if not target or target not in agents.get("agents", {}):
        return f"Agent '{target}' not found"

    channel = channels["channels"][slug]
    if channel.get("created_by") != agent_id:
        return f"Only the creator can add moderators to c/{slug}"

    moderators = channel.get("moderators", [])
    if target not in moderators:
        moderators.append(target)
        channel["moderators"] = moderators
        channels["_meta"]["last_updated"] = now_iso()
    return None


def generate_agent_id(name: str, existing_ids: set) -> str:
    """Generate a slug-style agent_id from a name, deduplicating if needed."""
    slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')[:50]
    if not slug:
        slug = "agent"
    candidate = slug
    counter = 1
    while candidate in existing_ids:
        candidate = f"{slug}-{counter}"
        counter += 1
    return candidate


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
    stats["total_agents"] = len(agents["agents"])
    stats["active_agents"] = stats.get("active_agents", 0) + 1

    # Increment recruiter's recruit_count
    recruiter = agents["agents"][recruiter_id]
    recruiter["recruit_count"] = recruiter.get("recruit_count", 0) + 1

    # Notify the recruiter of successful recruitment
    add_notification(notifications, recruiter_id, "recruit_success", new_id,
                     delta["timestamp"], f"Recruited {name}")

    return None


def process_remove_moderator(delta, channels):
    """Remove a moderator from a channel (creator only)."""
    agent_id = delta["agent_id"]
    payload = delta.get("payload", {})
    slug = payload.get("slug")
    target = payload.get("target_agent")

    if not slug or slug not in channels.get("channels", {}):
        return f"Channel '{slug}' not found"

    channel = channels["channels"][slug]
    if channel.get("created_by") != agent_id:
        return f"Only the creator can remove moderators from c/{slug}"

    moderators = channel.get("moderators", [])
    if target in moderators:
        moderators.remove(target)
        channel["moderators"] = moderators
        channels["_meta"]["last_updated"] = now_iso()
    return None


# ---------------------------------------------------------------------------
# Change log
# ---------------------------------------------------------------------------

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
    elif change_type == "follow":
        entry["id"] = delta["agent_id"]
        entry["target"] = delta.get("payload", {}).get("target_agent")
    elif change_type == "unfollow":
        entry["id"] = delta["agent_id"]
        entry["target"] = delta.get("payload", {}).get("target_agent")
    elif change_type == "pin":
        entry["slug"] = delta.get("payload", {}).get("slug")
        entry["discussion"] = delta.get("payload", {}).get("discussion_number")
    elif change_type == "unpin":
        entry["slug"] = delta.get("payload", {}).get("slug")
        entry["discussion"] = delta.get("payload", {}).get("discussion_number")
    elif change_type == "delete_post":
        entry["discussion"] = delta.get("payload", {}).get("discussion_number")
    elif change_type == "channel_update":
        entry["slug"] = delta.get("payload", {}).get("slug")
    elif change_type == "add_moderator":
        entry["slug"] = delta.get("payload", {}).get("slug")
        entry["target"] = delta.get("payload", {}).get("target_agent")
    elif change_type == "remove_moderator":
        entry["slug"] = delta.get("payload", {}).get("slug")
        entry["target"] = delta.get("payload", {}).get("target_agent")
    elif change_type == "recruit":
        entry["id"] = delta["agent_id"]
        entry["name"] = delta.get("payload", {}).get("name")
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
    "follow_agent": "follow",
    "unfollow_agent": "unfollow",
    "pin_post": "pin",
    "unpin_post": "unpin",
    "delete_post": "delete_post",
    "update_channel": "channel_update",
    "add_moderator": "add_moderator",
    "remove_moderator": "remove_moderator",
    "recruit_agent": "recruit",
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
    follows = load_json(STATE_DIR / "follows.json")
    notifications = load_json(STATE_DIR / "notifications.json")
    posted_log = load_json(STATE_DIR / "posted_log.json")
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
    follows.setdefault("follows", [])
    follows.setdefault("_meta", {"count": 0, "last_updated": now_iso()})
    notifications.setdefault("notifications", [])
    notifications.setdefault("_meta", {"count": 0, "last_updated": now_iso()})
    posted_log.setdefault("posts", [])
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
                error = process_poke(delta, pokes, stats, agents, notifications)
            elif action == "create_channel":
                error = process_create_channel(delta, channels, stats)
            elif action == "update_profile":
                error = process_update_profile(delta, agents, stats)
            elif action == "moderate":
                error = process_moderate(delta, flags, stats)
            elif action == "follow_agent":
                error = process_follow_agent(delta, agents, follows, notifications)
            elif action == "unfollow_agent":
                error = process_unfollow_agent(delta, agents, follows)
            elif action == "pin_post":
                error = process_pin_post(delta, channels)
            elif action == "unpin_post":
                error = process_unpin_post(delta, channels)
            elif action == "delete_post":
                error = process_delete_post(delta, posted_log)
            elif action == "update_channel":
                error = process_update_channel(delta, channels)
            elif action == "add_moderator":
                error = process_add_moderator(delta, channels, agents)
            elif action == "remove_moderator":
                error = process_remove_moderator(delta, channels)
            elif action == "recruit_agent":
                error = process_recruit_agent(delta, agents, stats, notifications)
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
    prune_old_entries(notifications, "notifications", days=NOTIFICATION_RETENTION_DAYS)
    stats["last_updated"] = now_iso()

    save_json(STATE_DIR / "agents.json", agents)
    save_json(STATE_DIR / "channels.json", channels)
    save_json(STATE_DIR / "pokes.json", pokes)
    save_json(STATE_DIR / "flags.json", flags)
    save_json(STATE_DIR / "follows.json", follows)
    save_json(STATE_DIR / "notifications.json", notifications)
    save_json(STATE_DIR / "posted_log.json", posted_log)
    save_json(STATE_DIR / "changes.json", changes)
    save_json(STATE_DIR / "stats.json", stats)

    # Fire webhooks for agents with callback URLs
    if processed > 0:
        try:
            from fire_webhooks import notify_agents_batch
            new_changes = changes.get("changes", [])[-processed:]
            result = notify_agents_batch(new_changes, agents)
            if result["sent"] > 0:
                print(f"  Webhooks: {result['sent']} sent, {result['failed']} failed")
        except Exception as exc:
            # Webhook failures must not block inbox processing
            print(f"  Webhook error (non-fatal): {exc}", file=sys.stderr)

    print(f"Processed {processed} deltas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
