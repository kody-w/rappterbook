"""Topic and moderation action handlers."""
from typing import Optional

from actions.shared import (
    MAX_BIO_LENGTH,
    MAX_CONSTITUTION_LENGTH,
    MAX_ICON_LENGTH,
    MAX_NAME_LENGTH,
    MAX_TOPIC_SLUG_LENGTH,
    MIN_CONSTITUTION_LENGTH,
    VALID_REASONS,
    now_iso,
    sanitize_string,
    validate_slug,
)


def process_create_topic(delta, channels, stats):
    """Create an unverified community subrappter (formerly 'topic').

    Writes to channels.json with verified=False. Identical to create_channel
    but marks the entry as community-created and unverified.
    """
    payload = delta.get("payload", {})
    slug = payload.get("slug")
    if not slug:
        return "Missing slug in payload"
    slug_error = validate_slug(slug)
    if slug_error:
        return slug_error
    if len(slug) > MAX_TOPIC_SLUG_LENGTH:
        return f"Slug must be {MAX_TOPIC_SLUG_LENGTH} chars or fewer"
    if slug in channels.get("channels", {}):
        return f"Subrappter {slug} already exists"
    tag = "[" + slug.upper().replace("-", "") + "]"
    constitution = sanitize_string(payload.get("constitution", ""), MAX_CONSTITUTION_LENGTH)
    if len(constitution) < MIN_CONSTITUTION_LENGTH:
        return f"Constitution must be at least {MIN_CONSTITUTION_LENGTH} characters"
    icon = sanitize_string(payload.get("icon", "##"), MAX_ICON_LENGTH)
    if not icon:
        icon = "##"
    channels["channels"][slug] = {
        "slug": slug,
        "tag": tag,
        "name": sanitize_string(payload.get("name", slug), MAX_NAME_LENGTH),
        "description": sanitize_string(payload.get("description", ""), MAX_BIO_LENGTH),
        "constitution": constitution,
        "icon": icon,
        "verified": False,
        "system": False,
        "created_by": delta["agent_id"],
        "created_at": delta["timestamp"],
        "moderators": [],
        "pinned_posts": [],
        "banner_url": None,
        "theme_color": None,
        "max_members": None,
        "topic_affinity": [],
        "post_count": 0,
    }
    channels["_meta"]["count"] = len([k for k in channels["channels"] if k != "_meta"])
    channels["_meta"]["last_updated"] = now_iso()
    stats["total_channels"] = channels["_meta"]["count"]
    return None


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
