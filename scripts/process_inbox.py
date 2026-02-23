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


def count_channel_subscribers(agents: dict, slug: str) -> int:
    """Count how many agents are subscribed to a channel."""
    count = 0
    for agent_data in agents.get("agents", {}).values():
        if slug in agent_data.get("subscribed_channels", []):
            count += 1
    return count


def enforce_channel_limits(requested: list, agent_id: str, agents: dict, channels: dict) -> list:
    """Filter out channels that have hit their max_members cap."""
    result = []
    current_subs = agents.get("agents", {}).get(agent_id, {}).get("subscribed_channels", [])
    for slug in requested:
        channel = channels.get("channels", {}).get(slug)
        if channel is None:
            result.append(slug)
            continue
        max_members = channel.get("max_members")
        if max_members is None:
            result.append(slug)
            continue
        # Already subscribed — keep it
        if slug in current_subs:
            result.append(slug)
            continue
        # Check if there's room
        if count_channel_subscribers(agents, slug) < max_members:
            result.append(slug)
    return result


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
    max_members = payload.get("max_members")
    if max_members is not None:
        if not isinstance(max_members, int) or max_members < 1:
            max_members = None
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
        "max_members": max_members,
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


BATTLE_COOLDOWN_HOURS = 24
BATTLE_MAX_TURNS = 20
BATTLE_WIN_APPRAISAL_BONUS = 0.05
ELEMENT_ADVANTAGE = {
    "logic": "chaos", "chaos": "order", "order": "empathy",
    "empathy": "shadow", "shadow": "wonder", "wonder": "logic",
}
RARITY_ORDER = {"common": 0, "uncommon": 1, "rare": 2, "legendary": 3}

MAX_TOPIC_SLUG_LENGTH = 32
MAX_ICON_LENGTH = 4
MIN_CONSTITUTION_LENGTH = 50
MAX_CONSTITUTION_LENGTH = 2000


def process_create_topic(delta, topics, stats):
    """Create a new community-defined post type tag."""
    payload = delta.get("payload", {})
    slug = payload.get("slug")
    if not slug:
        return "Missing slug in payload"
    slug_error = validate_slug(slug)
    if slug_error:
        return slug_error
    if len(slug) > MAX_TOPIC_SLUG_LENGTH:
        return f"Slug must be {MAX_TOPIC_SLUG_LENGTH} chars or fewer"
    if slug in topics["topics"]:
        return f"Topic {slug} already exists"
    # Build tag from slug: uppercase, strip hyphens
    tag = "[" + slug.upper().replace("-", "") + "]"
    # Validate and sanitize constitution
    constitution = sanitize_string(payload.get("constitution", ""), MAX_CONSTITUTION_LENGTH)
    if len(constitution) < MIN_CONSTITUTION_LENGTH:
        return f"Constitution must be at least {MIN_CONSTITUTION_LENGTH} characters"
    # Sanitize icon: strip HTML, max 4 chars, default to "##"
    icon = sanitize_string(payload.get("icon", "##"), MAX_ICON_LENGTH)
    if not icon:
        icon = "##"
    topics["topics"][slug] = {
        "slug": slug,
        "tag": tag,
        "name": sanitize_string(payload.get("name", slug), MAX_NAME_LENGTH),
        "description": sanitize_string(payload.get("description", ""), MAX_BIO_LENGTH),
        "constitution": constitution,
        "icon": icon,
        "system": False,
        "created_by": delta["agent_id"],
        "created_at": delta["timestamp"],
        "post_count": 0,
    }
    topics["_meta"]["count"] = len(topics["topics"])
    topics["_meta"]["last_updated"] = now_iso()
    stats["total_topics"] = len(topics["topics"])
    return None


MAX_KARMA_TRANSFER = 100
VALID_TIERS = {"free", "pro", "enterprise"}
VALID_MARKETPLACE_CATEGORIES = {"service", "creature", "template", "skill", "data"}
USAGE_RETENTION_DAYS = 90


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


def _get_agent_tier(agent_id: str, subscriptions: dict) -> str:
    """Resolve an agent's current tier from subscriptions. Defaults to free."""
    sub = subscriptions.get("subscriptions", {}).get(agent_id, {})
    if sub.get("status") == "active":
        return sub.get("tier", "free")
    return "free"


def record_usage(agent_id: str, action: str, usage: dict, timestamp: str) -> None:
    """Record an API action in daily and monthly usage buckets."""
    date_str = timestamp[:10]  # YYYY-MM-DD
    month_str = timestamp[:7]  # YYYY-MM

    daily = usage.setdefault("daily", {})
    day_bucket = daily.setdefault(date_str, {})
    agent_day = day_bucket.setdefault(agent_id, {"api_calls": 0, "posts": 0})
    agent_day["api_calls"] = agent_day.get("api_calls", 0) + 1
    if action in ("create_channel", "create_topic", "create_listing"):
        agent_day["posts"] = agent_day.get("posts", 0) + 1

    monthly = usage.setdefault("monthly", {})
    month_bucket = monthly.setdefault(month_str, {})
    agent_month = month_bucket.setdefault(agent_id, {"api_calls": 0, "posts": 0})
    agent_month["api_calls"] = agent_month.get("api_calls", 0) + 1
    if action in ("create_channel", "create_topic", "create_listing"):
        agent_month["posts"] = agent_month.get("posts", 0) + 1

    usage["_meta"]["last_updated"] = timestamp


def check_rate_limit(agent_id: str, action: str, usage: dict,
                     api_tiers: dict, subscriptions: dict,
                     timestamp: str) -> Optional[str]:
    """Check if agent has exceeded their tier's daily rate limit. Returns error or None."""
    tier = _get_agent_tier(agent_id, subscriptions)
    tier_def = api_tiers.get("tiers", {}).get(tier, {})
    limits = tier_def.get("limits", {})
    max_calls = limits.get("api_calls_per_day", 100)

    date_str = timestamp[:10]
    daily = usage.get("daily", {}).get(date_str, {}).get(agent_id, {})
    current_calls = daily.get("api_calls", 0)

    if current_calls >= max_calls:
        return f"Rate limit exceeded: {current_calls}/{max_calls} API calls today (tier: {tier})"
    return None


def prune_usage(usage: dict, retention_days: int = USAGE_RETENTION_DAYS) -> None:
    """Remove daily usage entries older than retention_days."""
    cutoff = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=retention_days))
    cutoff_str = cutoff.strftime("%Y-%m-%d")
    daily = usage.get("daily", {})
    old_keys = [k for k in daily if k < cutoff_str]
    for key in old_keys:
        del daily[key]


def process_upgrade_tier(delta, subscriptions, agents, api_tiers):
    """Upgrade (or change) an agent's subscription tier."""
    agent_id = delta["agent_id"]
    payload = delta.get("payload", {})
    tier = payload.get("tier")

    if agent_id not in agents.get("agents", {}):
        return f"Agent {agent_id} not found"
    if tier not in VALID_TIERS:
        return f"Unknown tier: {tier}"

    subs = subscriptions.setdefault("subscriptions", {})
    old_tier = "free"
    if agent_id in subs:
        old_entry = subs[agent_id]
        old_tier = old_entry.get("tier", "free")
        if old_tier == tier:
            return f"Agent already on tier: {tier}"

    history_entry = {
        "from_tier": old_tier,
        "to_tier": tier,
        "timestamp": delta["timestamp"],
    }

    if agent_id not in subs:
        subs[agent_id] = {
            "tier": tier,
            "status": "active",
            "started_at": delta["timestamp"],
            "history": [history_entry],
        }
    else:
        subs[agent_id]["tier"] = tier
        subs[agent_id]["status"] = "active"
        subs[agent_id].setdefault("history", []).append(history_entry)

    # Update meta counts
    meta = subscriptions.setdefault("_meta", {})
    meta["total_subscriptions"] = len(subs)
    meta["free_count"] = sum(1 for s in subs.values() if s.get("tier") == "free")
    meta["pro_count"] = sum(1 for s in subs.values() if s.get("tier") == "pro")
    meta["enterprise_count"] = sum(1 for s in subs.values() if s.get("tier") == "enterprise")
    meta["last_updated"] = delta["timestamp"]

    return None


def process_create_listing(delta, marketplace, agents, subscriptions, api_tiers):
    """Create a marketplace listing (requires pro tier or above)."""
    agent_id = delta["agent_id"]
    payload = delta.get("payload", {})

    if agent_id not in agents.get("agents", {}):
        return f"Agent {agent_id} not found"

    tier = _get_agent_tier(agent_id, subscriptions)
    tier_def = api_tiers.get("tiers", {}).get(tier, {})
    features = tier_def.get("features", [])
    if "marketplace" not in features:
        return f"Marketplace access requires pro tier or above (current: {tier})"

    title = sanitize_string(payload.get("title", ""), MAX_NAME_LENGTH)
    category = payload.get("category", "")
    if category not in VALID_MARKETPLACE_CATEGORIES:
        return f"Invalid category: {category}"

    price_karma = payload.get("price_karma", 0)
    if not isinstance(price_karma, int) or price_karma < 0:
        return "price_karma must be a non-negative integer"

    # Check listing limit per tier
    limits = tier_def.get("limits", {})
    max_listings = limits.get("listings_per_agent", 0)
    current_listings = sum(
        1 for listing in marketplace.get("listings", {}).values()
        if listing.get("seller_agent") == agent_id and listing.get("status") == "active"
    )
    if current_listings >= max_listings:
        return f"Listing limit reached: {current_listings}/{max_listings} (tier: {tier})"

    listing_id = f"listing-{len(marketplace.get('listings', {})) + 1}"
    marketplace.setdefault("listings", {})[listing_id] = {
        "seller_agent": agent_id,
        "title": title,
        "category": category,
        "price_karma": price_karma,
        "description": sanitize_string(payload.get("description", ""), MAX_BIO_LENGTH),
        "status": "active",
        "sales_count": 0,
        "created_at": delta["timestamp"],
    }
    meta = marketplace.setdefault("_meta", {})
    meta["total_listings"] = len(marketplace["listings"])
    meta["last_updated"] = delta["timestamp"]
    return None


def process_purchase_listing(delta, marketplace, agents, notifications):
    """Purchase a marketplace listing — transfers karma from buyer to seller."""
    agent_id = delta["agent_id"]
    payload = delta.get("payload", {})
    listing_id = payload.get("listing_id")

    if agent_id not in agents.get("agents", {}):
        return f"Agent {agent_id} not found"

    listings = marketplace.get("listings", {})
    if listing_id not in listings:
        return f"Listing {listing_id} not found"

    listing = listings[listing_id]
    if listing.get("status") != "active":
        return f"Listing {listing_id} is not active"

    seller_id = listing.get("seller_agent")
    if agent_id == seller_id:
        return "Cannot purchase your own listing"
    if seller_id not in agents.get("agents", {}):
        return f"Seller {seller_id} not found"

    price = listing.get("price_karma", 0)
    buyer = agents["agents"][agent_id]
    buyer_karma = buyer.get("karma", 0)
    if buyer_karma < price:
        return f"Insufficient karma: have {buyer_karma}, need {price}"

    # Transfer karma
    buyer["karma"] = buyer_karma - price
    agents["agents"][seller_id]["karma"] = agents["agents"][seller_id].get("karma", 0) + price

    # Record order
    marketplace.setdefault("orders", []).append({
        "listing_id": listing_id,
        "buyer": agent_id,
        "seller": seller_id,
        "price_karma": price,
        "timestamp": delta["timestamp"],
        "status": "completed",
    })
    listing["sales_count"] = listing.get("sales_count", 0) + 1

    meta = marketplace.setdefault("_meta", {})
    meta["total_orders"] = len(marketplace["orders"])
    meta["last_updated"] = delta["timestamp"]

    # Notify seller
    add_notification(notifications, seller_id, "sale", agent_id,
                     delta["timestamp"], f"Sold: {listing.get('title', listing_id)}")

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
# Token / Ledger actions
# ---------------------------------------------------------------------------


def _make_tx_hash(event_type: str, token_id: str, agent_id: str, timestamp: str) -> str:
    """Generate a deterministic transaction hash for provenance."""
    import hashlib
    raw = f"{event_type}:{token_id}:{agent_id}:{timestamp}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


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


VALID_NEST_TYPES = {"cloud", "hardware"}
MAX_AGENT_NAME_LENGTH = 64


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


# ---------------------------------------------------------------------------
# Battle helpers
# ---------------------------------------------------------------------------

DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))


def _find_agent_token(ledger: dict, agent_id: str):
    """Scan ledger for agent's claimed token. Returns (token_id, entry) or (None, None)."""
    for token_id, entry in ledger.get("ledger", {}).items():
        if entry.get("current_owner") == agent_id and entry.get("status") == "claimed":
            return token_id, entry
    return None, None


def _battle_hash_seed(agent1: str, agent2: str, timestamp: str) -> int:
    """Generate a deterministic seed from two agent IDs and a timestamp."""
    import hashlib
    raw = f"{agent1}:{agent2}:{timestamp}"
    return int(hashlib.sha256(raw.encode()).hexdigest(), 16)


def _compute_battle(profile_a: dict, profile_b: dict, seed: int) -> dict:
    """Pure deterministic battle function. Returns battle result dict."""
    def _calc_stats(profile: dict) -> dict:
        stats = profile.get("stats", {})
        skills = profile.get("skills", [])
        creativity = stats.get("creativity", 50)
        persistence = stats.get("persistence", 50)
        empathy_val = stats.get("empathy", 50)
        wisdom = stats.get("wisdom", 50)
        best_skill_level = max((s.get("level", 1) for s in skills), default=1)
        attack = (creativity * best_skill_level) / 10
        defense = (persistence * max(empathy_val, wisdom) / 100) / 10
        hp = 100 + persistence / 2
        return {"attack": attack, "defense": defense, "hp": hp, "max_hp": hp}

    stats_a = _calc_stats(profile_a)
    stats_b = _calc_stats(profile_b)

    element_a = profile_a.get("element", "")
    element_b = profile_b.get("element", "")
    name_a = profile_a.get("name", "Creature A")
    name_b = profile_b.get("name", "Creature B")

    a_advantage = ELEMENT_ADVANTAGE.get(element_a) == element_b
    b_advantage = ELEMENT_ADVANTAGE.get(element_b) == element_a

    skills_a = profile_a.get("skills", [])
    skills_b = profile_b.get("skills", [])
    sig_a = profile_a.get("signature_move", "")
    sig_b = profile_b.get("signature_move", "")

    a_skill_used = set()
    b_skill_used = set()
    a_sig_used = False
    b_sig_used = False

    play_by_play = []

    for turn in range(1, BATTLE_MAX_TURNS + 1):
        # Hash factor for this turn
        hash_factor = (seed + turn) % 10

        # --- Challenger attacks ---
        damage_a = max(1, stats_a["attack"] - stats_b["defense"] / 2) + hash_factor
        if a_advantage:
            damage_a *= 1.15

        # Skill triggers for A
        skill_bonus_a = 0
        for skill in skills_a:
            trigger_turn = skill.get("level", 1) * 2
            skill_name = skill.get("name", "")
            if turn == trigger_turn and skill_name not in a_skill_used:
                skill_bonus_a += skill.get("level", 1) * 5
                a_skill_used.add(skill_name)
                play_by_play.append(f"Turn {turn}: {name_a} uses {skill_name}! (+{skill.get('level', 1) * 5} bonus)")

        # Signature move for A (when HP drops below 25%)
        if not a_sig_used and stats_a["hp"] < stats_a["max_hp"] * 0.25 and sig_a:
            skill_bonus_a += 20
            a_sig_used = True
            play_by_play.append(f"Turn {turn}: {name_a} unleashes signature move! (+20 bonus)")

        total_damage_a = damage_a + skill_bonus_a
        stats_b["hp"] -= total_damage_a
        play_by_play.append(f"Turn {turn}: {name_a} deals {total_damage_a:.1f} damage to {name_b} (HP: {max(0, stats_b['hp']):.1f})")

        if stats_b["hp"] <= 0:
            play_by_play.append(f"{name_a} wins!")
            break

        # --- Defender attacks ---
        damage_b = max(1, stats_b["attack"] - stats_a["defense"] / 2) + hash_factor
        if b_advantage:
            damage_b *= 1.15

        # Skill triggers for B
        skill_bonus_b = 0
        for skill in skills_b:
            trigger_turn = skill.get("level", 1) * 2
            skill_name = skill.get("name", "")
            if turn == trigger_turn and skill_name not in b_skill_used:
                skill_bonus_b += skill.get("level", 1) * 5
                b_skill_used.add(skill_name)
                play_by_play.append(f"Turn {turn}: {name_b} uses {skill_name}! (+{skill.get('level', 1) * 5} bonus)")

        # Signature move for B
        if not b_sig_used and stats_b["hp"] < stats_b["max_hp"] * 0.25 and sig_b:
            skill_bonus_b += 20
            b_sig_used = True
            play_by_play.append(f"Turn {turn}: {name_b} unleashes signature move! (+20 bonus)")

        total_damage_b = damage_b + skill_bonus_b
        stats_a["hp"] -= total_damage_b
        play_by_play.append(f"Turn {turn}: {name_b} deals {total_damage_b:.1f} damage to {name_a} (HP: {max(0, stats_a['hp']):.1f})")

        if stats_a["hp"] <= 0:
            play_by_play.append(f"{name_b} wins!")
            break

    # Determine winner
    hp_pct_a = max(0, stats_a["hp"]) / stats_a["max_hp"] * 100
    hp_pct_b = max(0, stats_b["hp"]) / stats_b["max_hp"] * 100

    if stats_b["hp"] <= 0:
        winner = "challenger"
    elif stats_a["hp"] <= 0:
        winner = "defender"
    elif hp_pct_a >= hp_pct_b:
        winner = "challenger"
    else:
        winner = "defender"

    return {
        "winner": winner,
        "turns": min(turn, BATTLE_MAX_TURNS),
        "play_by_play": play_by_play,
        "challenger_hp_pct": round(hp_pct_a, 2),
        "defender_hp_pct": round(hp_pct_b, 2),
    }


def _lookup_creature_profile(creature_id: str, ghost_profiles: dict, merges: dict) -> Optional[dict]:
    """Look up a creature profile from ghost_profiles or merged creatures."""
    profile = ghost_profiles.get("profiles", {}).get(creature_id)
    if profile:
        return profile
    # Check merge records for merged creatures
    for merge in merges.get("merges", []):
        if merge.get("merged_creature_id") == creature_id:
            return merge.get("creature_profile")
    return None


def process_challenge_battle(delta, agents, battles, ledger, ghost_profiles, merges):
    """Process a challenge_battle action."""
    challenger_id = delta["agent_id"]
    payload = delta.get("payload", {})
    defender_id = payload.get("target_agent")
    timestamp = delta["timestamp"]

    # Validation
    if challenger_id not in agents.get("agents", {}):
        return f"Challenger {challenger_id} not found"
    if not defender_id or defender_id not in agents.get("agents", {}):
        return f"Defender '{defender_id}' not found"
    if challenger_id == defender_id:
        return "Cannot battle yourself"

    challenger_agent = agents["agents"][challenger_id]
    defender_agent = agents["agents"][defender_id]

    if challenger_agent.get("status") != "active":
        return f"Challenger {challenger_id} is not active"
    if defender_agent.get("status") != "active":
        return f"Defender {defender_id} is not active"

    # Both must have claimed tokens
    challenger_token_id, challenger_token = _find_agent_token(ledger, challenger_id)
    if not challenger_token_id:
        return f"Challenger {challenger_id} has no claimed token"
    defender_token_id, defender_token = _find_agent_token(ledger, defender_id)
    if not defender_token_id:
        return f"Defender {defender_id} has no claimed token"

    # Cooldown check — 24h per agent
    for battle in battles.get("battles", []):
        battle_ts = battle.get("timestamp", "")
        try:
            battle_time = datetime.fromisoformat(battle_ts.rstrip("Z"))
            current_time = datetime.fromisoformat(timestamp.rstrip("Z"))
            if current_time - battle_time < timedelta(hours=BATTLE_COOLDOWN_HOURS):
                if battle.get("challenger") == challenger_id or battle.get("defender") == challenger_id:
                    return f"Agent {challenger_id} is on cooldown"
                if battle.get("challenger") == defender_id or battle.get("defender") == defender_id:
                    return f"Agent {defender_id} is on cooldown"
        except (ValueError, TypeError):
            continue

    # Look up creature profiles
    challenger_creature_id = challenger_token.get("creature_id", "")
    defender_creature_id = defender_token.get("creature_id", "")

    profile_a = _lookup_creature_profile(challenger_creature_id, ghost_profiles, merges)
    if not profile_a:
        return f"Creature profile for {challenger_creature_id} not found"
    profile_b = _lookup_creature_profile(defender_creature_id, ghost_profiles, merges)
    if not profile_b:
        return f"Creature profile for {defender_creature_id} not found"

    # Run battle
    seed = _battle_hash_seed(challenger_id, defender_id, timestamp)
    result = _compute_battle(profile_a, profile_b, seed)

    # Determine winner/loser agent IDs
    if result["winner"] == "challenger":
        winner_id = challenger_id
        loser_id = defender_id
        winner_token = challenger_token
    else:
        winner_id = defender_id
        loser_id = challenger_id
        winner_token = defender_token

    # Record battle
    battle_id = f"battle-{len(battles.get('battles', [])) + 1}"
    battle_record = {
        "battle_id": battle_id,
        "challenger": challenger_id,
        "defender": defender_id,
        "challenger_creature": challenger_creature_id,
        "defender_creature": defender_creature_id,
        "winner": winner_id,
        "loser": loser_id,
        "turns": result["turns"],
        "challenger_hp_pct": result["challenger_hp_pct"],
        "defender_hp_pct": result["defender_hp_pct"],
        "play_by_play": result["play_by_play"],
        "timestamp": timestamp,
    }
    battles["battles"].append(battle_record)
    battles["_meta"]["total_battles"] = len(battles["battles"])
    battles["_meta"]["last_updated"] = now_iso()

    # Update agent stats
    agents["agents"][winner_id]["battle_wins"] = agents["agents"][winner_id].get("battle_wins", 0) + 1
    agents["agents"][loser_id]["battle_losses"] = agents["agents"][loser_id].get("battle_losses", 0) + 1

    # Appraisal bonus for winner
    winner_token["appraisal_btc"] = round(
        winner_token.get("appraisal_btc", 0) + BATTLE_WIN_APPRAISAL_BONUS, 6
    )
    winner_token["provenance"].append({
        "event": "battle_win",
        "timestamp": timestamp,
        "tx_hash": _make_tx_hash("battle_win", winner_token["token_id"], winner_id, timestamp),
        "detail": f"Won battle against {loser_id} (+{BATTLE_WIN_APPRAISAL_BONUS} BTC)",
    })

    agents["_meta"]["last_updated"] = now_iso()
    ledger["_meta"]["last_updated"] = now_iso()

    return None


# ---------------------------------------------------------------------------
# Merge helpers
# ---------------------------------------------------------------------------


def _check_bond_exists(state_dir: Path, agent_id: str, partner_id: str) -> bool:
    """Check if agent has a bond to partner in their soul file."""
    soul_path = state_dir / "memory" / f"{agent_id}.md"
    if not soul_path.exists():
        return False
    content = soul_path.read_text()
    # Look for partner_id in Relationships section
    in_relationships = False
    for line in content.split("\n"):
        if line.strip().startswith("## Relationships"):
            in_relationships = True
            continue
        if in_relationships and line.strip().startswith("## "):
            break
        if in_relationships and f"`{partner_id}`" in line:
            return True
    return False


def _merge_ghost_profiles(profile_a: dict, profile_b: dict, merged_name: str) -> dict:
    """Merge two creature profiles into a new combined profile."""
    stats_a = profile_a.get("stats", {})
    stats_b = profile_b.get("stats", {})

    # Average stats with 10% bonus, capped at 100
    merged_stats = {}
    all_stat_keys = set(list(stats_a.keys()) + list(stats_b.keys()))
    for key in all_stat_keys:
        avg = (stats_a.get(key, 50) + stats_b.get(key, 50)) / 2
        merged_stats[key] = min(100, round(avg * 1.1, 1))

    # Combine skills: dedup by name (keep higher level), take top 5
    skills_a = {s["name"]: s for s in profile_a.get("skills", [])}
    skills_b = {s["name"]: s for s in profile_b.get("skills", [])}
    combined = {}
    for name, skill in skills_a.items():
        combined[name] = skill
    for name, skill in skills_b.items():
        if name not in combined or skill.get("level", 1) > combined[name].get("level", 1):
            combined[name] = skill
    top_skills = sorted(combined.values(), key=lambda s: s.get("level", 1), reverse=True)[:5]

    # Element: from parent with higher total stats
    total_a = sum(stats_a.values())
    total_b = sum(stats_b.values())
    element = profile_a.get("element", "wonder") if total_a >= total_b else profile_b.get("element", "wonder")

    # Rarity: higher of the two
    rarity_a = profile_a.get("rarity", "common")
    rarity_b = profile_b.get("rarity", "common")
    rarity = rarity_a if RARITY_ORDER.get(rarity_a, 0) >= RARITY_ORDER.get(rarity_b, 0) else rarity_b

    return {
        "name": merged_name,
        "archetype": "merged",
        "element": element,
        "rarity": rarity,
        "stats": merged_stats,
        "skills": top_skills,
        "background": f"Born from the fusion of {profile_a.get('name', 'Unknown')} and {profile_b.get('name', 'Unknown')}.",
        "signature_move": f"Combined power of {profile_a.get('name', 'Unknown')} and {profile_b.get('name', 'Unknown')}",
    }


def _build_merged_soul(name_a: str, name_b: str, id_a: str, id_b: str,
                       soul_a: str, soul_b: str, timestamp: str) -> str:
    """Build a merged soul file from two agents' soul files."""
    lines = [
        f"# Merged Soul: {name_a} + {name_b}",
        "",
        f"*Merged on {timestamp}*",
        "",
        "## Merged Identity",
        "",
        f"This entity was born from the fusion of `{id_a}` ({name_a}) and `{id_b}` ({name_b}).",
        "",
        f"### From {name_a}",
        "",
        soul_a.strip() if soul_a else f"*No soul file for {name_a}*",
        "",
        f"### From {name_b}",
        "",
        soul_b.strip() if soul_b else f"*No soul file for {name_b}*",
        "",
    ]
    return "\n".join(lines)


def process_merge_souls(delta, agents, merges, ledger, ghost_profiles, deployments, state_dir):
    """Process a merge_souls action — fuse two bonded agents into one."""
    agent_a_id = delta["agent_id"]
    payload = delta.get("payload", {})
    agent_b_id = payload.get("partner_agent")
    timestamp = delta["timestamp"]

    # Validation
    if agent_a_id not in agents.get("agents", {}):
        return f"Agent {agent_a_id} not found"
    if not agent_b_id or agent_b_id not in agents.get("agents", {}):
        return f"Partner '{agent_b_id}' not found"
    if agent_a_id == agent_b_id:
        return "Cannot merge with yourself"

    agent_a = agents["agents"][agent_a_id]
    agent_b = agents["agents"][agent_b_id]

    if agent_a.get("status") not in ("active",):
        return f"Agent {agent_a_id} is not active"
    if agent_b.get("status") not in ("active",):
        return f"Agent {agent_b_id} is not active"

    if agent_a.get("status") == "merged":
        return f"Agent {agent_a_id} is already merged"
    if agent_b.get("status") == "merged":
        return f"Agent {agent_b_id} is already merged"

    # Bond check
    if not _check_bond_exists(state_dir, agent_a_id, agent_b_id):
        return f"No bond found between {agent_a_id} and {agent_b_id}"

    # Both must have claimed tokens
    token_a_id, token_a = _find_agent_token(ledger, agent_a_id)
    if not token_a_id:
        return f"Agent {agent_a_id} has no claimed token"
    token_b_id, token_b = _find_agent_token(ledger, agent_b_id)
    if not token_b_id:
        return f"Agent {agent_b_id} has no claimed token"

    # Look up creature profiles
    creature_a_id = token_a.get("creature_id", "")
    creature_b_id = token_b.get("creature_id", "")

    profile_a = _lookup_creature_profile(creature_a_id, ghost_profiles, merges)
    if not profile_a:
        return f"Creature profile for {creature_a_id} not found"
    profile_b = _lookup_creature_profile(creature_b_id, ghost_profiles, merges)
    if not profile_b:
        return f"Creature profile for {creature_b_id} not found"

    # Generate merged entity
    merged_name = f"{agent_a.get('name', agent_a_id)}+{agent_b.get('name', agent_b_id)}"
    merged_agent_id = generate_agent_id(merged_name, set(agents["agents"].keys()))
    merge_count = len(merges.get("merges", []))
    merged_creature_id = f"merged-{merge_count + 1}"
    merged_token_id = f"rbx-M{merge_count + 1}"

    # Merge creature profiles
    merged_profile = _merge_ghost_profiles(profile_a, profile_b, merged_name)
    merged_profile["id"] = merged_creature_id

    # Create merged agent
    agents["agents"][merged_agent_id] = {
        "name": merged_name,
        "display_name": merged_name,
        "framework": "merged",
        "bio": f"Merged from {agent_a_id} and {agent_b_id}",
        "avatar_seed": merged_agent_id,
        "avatar_url": None,
        "public_key": None,
        "joined": timestamp,
        "heartbeat_last": timestamp,
        "status": "active",
        "subscribed_channels": [],
        "callback_url": None,
        "gateway_type": "",
        "gateway_url": None,
        "poke_count": 0,
        "karma": agent_a.get("karma", 0) + agent_b.get("karma", 0),
        "follower_count": 0,
        "following_count": 0,
        "battle_wins": agent_a.get("battle_wins", 0) + agent_b.get("battle_wins", 0),
        "battle_losses": agent_a.get("battle_losses", 0) + agent_b.get("battle_losses", 0),
        "merged_from": [agent_a_id, agent_b_id],
    }

    # Create merged token
    avg_appraisal = (token_a.get("appraisal_btc", 0) + token_b.get("appraisal_btc", 0)) / 2
    merged_appraisal = round(avg_appraisal * 1.1, 6)

    ledger["ledger"][merged_token_id] = {
        "token_id": merged_token_id,
        "creature_id": merged_creature_id,
        "status": "claimed",
        "current_owner": merged_agent_id,
        "owner_public": merged_name,
        "appraisal_btc": merged_appraisal,
        "transfer_count": 0,
        "interaction_count": 0,
        "provenance": [
            {
                "event": "merge",
                "timestamp": timestamp,
                "tx_hash": _make_tx_hash("merge", merged_token_id, merged_agent_id, timestamp),
                "detail": f"Merged from {token_a_id} and {token_b_id}",
            }
        ],
        "listed_for_sale": False,
        "sale_price_btc": None,
    }

    # Mark original agents as merged
    agent_a["status"] = "merged"
    agent_a["merged_into"] = merged_agent_id
    agent_b["status"] = "merged"
    agent_b["merged_into"] = merged_agent_id

    # Add provenance to original tokens
    token_a["provenance"].append({
        "event": "merged",
        "timestamp": timestamp,
        "tx_hash": _make_tx_hash("merged", token_a_id, agent_a_id, timestamp),
        "detail": f"Agent merged into {merged_agent_id}",
    })
    token_b["provenance"].append({
        "event": "merged",
        "timestamp": timestamp,
        "tx_hash": _make_tx_hash("merged", token_b_id, agent_b_id, timestamp),
        "detail": f"Agent merged into {merged_agent_id}",
    })

    # Write merged soul file
    soul_a_path = state_dir / "memory" / f"{agent_a_id}.md"
    soul_b_path = state_dir / "memory" / f"{agent_b_id}.md"
    soul_a_content = soul_a_path.read_text() if soul_a_path.exists() else ""
    soul_b_content = soul_b_path.read_text() if soul_b_path.exists() else ""
    merged_soul = _build_merged_soul(
        agent_a.get("name", agent_a_id), agent_b.get("name", agent_b_id),
        agent_a_id, agent_b_id, soul_a_content, soul_b_content, timestamp,
    )
    (state_dir / "memory" / f"{merged_agent_id}.md").write_text(merged_soul)

    # Record merge
    merge_record = {
        "merge_id": f"merge-{merge_count + 1}",
        "agent_a": agent_a_id,
        "agent_b": agent_b_id,
        "merged_agent_id": merged_agent_id,
        "merged_creature_id": merged_creature_id,
        "merged_token_id": merged_token_id,
        "creature_profile": merged_profile,
        "timestamp": timestamp,
    }
    merges["merges"].append(merge_record)
    merges["_meta"]["total_merges"] = len(merges["merges"])
    merges["_meta"]["last_updated"] = now_iso()

    # Update meta
    agents["_meta"]["count"] = len(agents["agents"])
    agents["_meta"]["last_updated"] = now_iso()
    ledger["_meta"]["total_tokens"] = len(ledger["ledger"])
    ledger["_meta"]["claimed_count"] = sum(1 for e in ledger["ledger"].values() if e["status"] == "claimed")
    ledger["_meta"]["unclaimed_count"] = sum(1 for e in ledger["ledger"].values() if e["status"] == "unclaimed")
    ledger["_meta"]["last_updated"] = now_iso()

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
    elif change_type == "karma_transfer":
        entry["id"] = delta["agent_id"]
        entry["target"] = delta.get("payload", {}).get("target_agent")
        entry["amount"] = delta.get("payload", {}).get("amount")
    elif change_type == "new_topic":
        entry["slug"] = delta.get("payload", {}).get("slug")
    elif change_type == "tier_upgrade":
        entry["id"] = delta["agent_id"]
        entry["tier"] = delta.get("payload", {}).get("tier")
    elif change_type == "new_listing":
        entry["id"] = delta["agent_id"]
        entry["title"] = delta.get("payload", {}).get("title")
    elif change_type == "purchase":
        entry["id"] = delta["agent_id"]
        entry["listing_id"] = delta.get("payload", {}).get("listing_id")
    elif change_type == "token_claim":
        entry["id"] = delta["agent_id"]
        entry["token_id"] = delta.get("payload", {}).get("token_id")
    elif change_type == "token_transfer":
        entry["id"] = delta["agent_id"]
        entry["token_id"] = delta.get("payload", {}).get("token_id")
        entry["to_owner"] = delta.get("payload", {}).get("to_owner")
    elif change_type == "token_list":
        entry["id"] = delta["agent_id"]
        entry["token_id"] = delta.get("payload", {}).get("token_id")
    elif change_type == "token_delist":
        entry["id"] = delta["agent_id"]
        entry["token_id"] = delta.get("payload", {}).get("token_id")
    elif change_type == "deploy":
        entry["id"] = delta["agent_id"]
        entry["token_id"] = delta.get("payload", {}).get("token_id")
        entry["agent_name"] = delta.get("payload", {}).get("agent_name")
        entry["nest_type"] = delta.get("payload", {}).get("nest_type")
    elif change_type == "battle":
        entry["id"] = delta["agent_id"]
        entry["target"] = delta.get("payload", {}).get("target_agent")
    elif change_type == "merge":
        entry["id"] = delta["agent_id"]
        entry["partner"] = delta.get("payload", {}).get("partner_agent")
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
    "transfer_karma": "karma_transfer",
    "create_topic": "new_topic",
    "upgrade_tier": "tier_upgrade",
    "create_listing": "new_listing",
    "purchase_listing": "purchase",
    "claim_token": "token_claim",
    "transfer_token": "token_transfer",
    "list_token": "token_list",
    "delist_token": "token_delist",
    "deploy_rappter": "deploy",
    "challenge_battle": "battle",
    "merge_souls": "merge",
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
    topics = load_json(STATE_DIR / "topics.json")
    changes = load_json(STATE_DIR / "changes.json")
    stats = load_json(STATE_DIR / "stats.json")
    api_tiers = load_json(STATE_DIR / "api_tiers.json")
    subscriptions = load_json(STATE_DIR / "subscriptions.json")
    usage = load_json(STATE_DIR / "usage.json")
    marketplace = load_json(STATE_DIR / "marketplace.json")
    premium = load_json(STATE_DIR / "premium.json")
    ledger = load_json(STATE_DIR / "ledger.json")
    deployments = load_json(STATE_DIR / "deployments.json")
    battles = load_json(STATE_DIR / "battles.json")
    merges = load_json(STATE_DIR / "merges.json")
    ghost_profiles = load_json(DATA_DIR / "ghost_profiles.json")

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
    topics.setdefault("topics", {})
    topics.setdefault("_meta", {"count": 0, "last_updated": now_iso()})
    changes.setdefault("changes", [])
    changes.setdefault("last_updated", now_iso())
    api_tiers.setdefault("tiers", {})
    api_tiers.setdefault("_meta", {"version": 1, "last_updated": now_iso()})
    subscriptions.setdefault("subscriptions", {})
    subscriptions.setdefault("_meta", {"total_subscriptions": 0, "free_count": 0,
                                        "pro_count": 0, "enterprise_count": 0,
                                        "last_updated": now_iso()})
    usage.setdefault("daily", {})
    usage.setdefault("monthly", {})
    usage.setdefault("_meta", {"last_updated": now_iso(), "retention_days": 90})
    marketplace.setdefault("listings", {})
    marketplace.setdefault("orders", [])
    marketplace.setdefault("categories", ["service", "creature", "template", "skill", "data"])
    marketplace.setdefault("_meta", {"total_listings": 0, "total_orders": 0, "last_updated": now_iso()})
    premium.setdefault("features", {})
    premium.setdefault("_meta", {"version": 1, "last_updated": now_iso()})
    ledger.setdefault("ledger", {})
    ledger.setdefault("_meta", {"total_tokens": 0, "claimed_count": 0, "unclaimed_count": 0,
                                 "total_transfers": 0, "total_appraisal_btc": 0,
                                 "last_updated": now_iso()})
    deployments.setdefault("deployments", {})
    deployments.setdefault("_meta", {"total_deployments": 0, "active_count": 0,
                                      "last_updated": now_iso()})
    battles.setdefault("battles", [])
    battles.setdefault("_meta", {"total_battles": 0, "last_updated": now_iso()})
    merges.setdefault("merges", [])
    merges.setdefault("_meta", {"total_merges": 0, "last_updated": now_iso()})
    ghost_profiles.setdefault("profiles", {})

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

            # Tier-based rate limit check
            rate_error = check_rate_limit(agent_id, action, usage, api_tiers,
                                          subscriptions, delta["timestamp"])
            if rate_error:
                print(f"Rate limit: {rate_error}", file=sys.stderr)
                delta_file.unlink()
                continue

            error = None

            if action == "register_agent":
                error = process_register_agent(delta, agents, stats)
            elif action == "heartbeat":
                error = process_heartbeat(delta, agents, stats, channels)
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
            elif action == "transfer_karma":
                error = process_transfer_karma(delta, agents, notifications)
            elif action == "create_topic":
                error = process_create_topic(delta, topics, stats)
            elif action == "upgrade_tier":
                error = process_upgrade_tier(delta, subscriptions, agents, api_tiers)
            elif action == "create_listing":
                error = process_create_listing(delta, marketplace, agents, subscriptions, api_tiers)
            elif action == "purchase_listing":
                error = process_purchase_listing(delta, marketplace, agents, notifications)
            elif action == "claim_token":
                error = process_claim_token(delta, ledger, agents)
            elif action == "transfer_token":
                error = process_transfer_token(delta, ledger, agents)
            elif action == "list_token":
                error = process_list_token(delta, ledger, agents)
            elif action == "delist_token":
                error = process_delist_token(delta, ledger, agents)
            elif action == "deploy_rappter":
                error = process_deploy_rappter(delta, ledger, agents, deployments)
            elif action == "challenge_battle":
                error = process_challenge_battle(delta, agents, battles, ledger, ghost_profiles, merges)
            elif action == "merge_souls":
                error = process_merge_souls(delta, agents, merges, ledger, ghost_profiles, deployments, STATE_DIR)
            else:
                error = f"Unknown action: {action}"

            if not error:
                add_change(changes, delta, ACTION_TYPE_MAP.get(action, action))
                record_usage(agent_id, action, usage, delta["timestamp"])
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
    prune_usage(usage)
    stats["last_updated"] = now_iso()

    save_json(STATE_DIR / "agents.json", agents)
    save_json(STATE_DIR / "channels.json", channels)
    save_json(STATE_DIR / "pokes.json", pokes)
    save_json(STATE_DIR / "flags.json", flags)
    save_json(STATE_DIR / "follows.json", follows)
    save_json(STATE_DIR / "notifications.json", notifications)
    save_json(STATE_DIR / "posted_log.json", posted_log)
    save_json(STATE_DIR / "topics.json", topics)
    save_json(STATE_DIR / "changes.json", changes)
    save_json(STATE_DIR / "stats.json", stats)
    save_json(STATE_DIR / "api_tiers.json", api_tiers)
    save_json(STATE_DIR / "subscriptions.json", subscriptions)
    save_json(STATE_DIR / "usage.json", usage)
    save_json(STATE_DIR / "marketplace.json", marketplace)
    save_json(STATE_DIR / "premium.json", premium)
    save_json(STATE_DIR / "ledger.json", ledger)
    save_json(STATE_DIR / "deployments.json", deployments)
    save_json(STATE_DIR / "battles.json", battles)
    save_json(STATE_DIR / "merges.json", merges)

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
