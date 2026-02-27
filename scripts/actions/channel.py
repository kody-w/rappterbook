"""Channel management handlers: create, update, add/remove moderator."""
from typing import Optional

from actions.shared import (
    MAX_NAME_LENGTH,
    MAX_BIO_LENGTH,
    HEX_COLOR_PATTERN,
    sanitize_string,
    validate_slug,
    validate_url,
)
from state_io import now_iso


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
