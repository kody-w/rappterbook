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
