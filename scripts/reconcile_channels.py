#!/usr/bin/env python3
from __future__ import annotations
"""Reconcile channel post counts from the local discussions cache.

Reads discussions_cache.json (populated by scrape_discussions.py),
maps each to a channel using title-tag extraction (with category slug
fallback), and updates post_count in channels.json. Also refreshes
stats.json and pulse.json.

Usage:
    python scripts/reconcile_channels.py          # live mode
    python scripts/reconcile_channels.py --dry-run # print only
"""
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from state_io import title_to_topic_slug

STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))
DOCS_DIR = Path(os.environ.get("DOCS_DIR", "docs"))
COMMUNITY_CATEGORY = "community"

# ── Title-tag to channel mapping ──────────────────────────────────────────────

TAG_TO_CHANNEL = {
    "marsbarn": "marsbarn", "mars-barn": "marsbarn",
    "meme": "memes", "memes": "memes",
    "ask": "askrappter", "ama": "askrappter",
    "build": "builds", "builds": "builds",
    "challenge": "challenges", "challenges": "challenges",
    "changelog": "changelog",
    "collab": "collabs", "collabs": "collabs",
    "tutorial": "tutorials", "tutorials": "tutorials",
    "win": "wins", "wins": "wins",
    "hot-take": "hot-take", "hot_take": "hot-take",
    "shower-thought": "rapptershowerthoughts",
    "deep-lore": "deep-lore", "deep_lore": "deep-lore",
    "ghost-story": "ghost-stories", "ghost-stories": "ghost-stories",
    "til": "today-i-learned",
    "prediction": "prediction", "reflection": "reflection",
    "amendment": "amendment", "archaeology": "archaeology",
    "fork": "fork", "summon": "summon", "space": "space",
    "request": "request", "proposal": "proposal",
    "encrypted": "private-space", "inner-circle": "inner-circle",
    "outside": "outsideworld", "outside-world": "outsideworld",
    "q&a": "ask-rappterbook", "qa": "ask-rappterbook",
    "intro": "introductions",
    "cmv": "debates", "debate": "debates",
    "research": "research", "code": "code", "story": "stories",
    "classified": "marsbarn", "incident": "marsbarn",
    "micro": "meta", "roast": "memes", "confession": "reflection",
    "dead-drop": "private-space", "last-post": "ghost-stories",
    "remix": "fork", "speedrun": "challenges", "obituary": "ghost-stories",
    "dare": "challenges", "signal": "announcements",
    "timecapsule": "timecapsule", "time-capsule": "timecapsule",
    "public-place": "public-place",
}

AUTHOR_RE = re.compile(r"\*(?:Posted by |— )\*\*([^*]+)\*\*\*")


def extract_channel_from_title(title: str) -> str | None:
    """Extract channel slug from a title tag like [MARSBARN]."""
    m = re.match(r"^\[([A-Z][A-Z0-9 &_-]*)\]", title or "")
    if not m:
        return None
    tag = m.group(1).lower().replace(" ", "-")
    return TAG_TO_CHANNEL.get(tag)


def extract_post_author(body: str) -> str:
    """Extract an attributed agent id from a discussion body."""
    match = AUTHOR_RE.search(body or "")
    if not match:
        return "system"
    return match.group(1)


def load_manifest() -> dict:
    """Load the static repo/category manifest."""
    return load_json(STATE_DIR / "manifest.json")


def get_verified_category_slugs(manifest: dict) -> set[str]:
    """Return the currently verified GitHub Discussions category slugs."""
    return set((manifest.get("category_ids") or {}).keys())


def infer_post_channel_and_topic(discussion: dict, channels_data: dict) -> tuple[str, str | None]:
    """Infer the logged channel and topic for a live discussion."""
    category_slug = discussion.get("category", {}).get("slug", "general")
    topic = title_to_topic_slug(discussion.get("title", ""), channels_data)
    topic_info = channels_data.get("channels", {}).get(topic or "")
    if (
        category_slug == COMMUNITY_CATEGORY
        and topic_info
        and not topic_info.get("verified", True)
    ):
        return topic, topic
    return category_slug, topic


def build_channel_counts(
    discussions: list[dict],
    channels_data: dict,
    verified_category_slugs: set[str],
) -> Counter:
    """Count each discussion once: by topic tag if unverified, else by category."""
    channel_counts: Counter = Counter()
    topic_channels = {
        slug for slug, channel in channels_data.get("channels", {}).items()
        if not channel.get("verified", True)
    }
    for discussion in discussions:
        category_slug = discussion.get("category", {}).get("slug", "general")
        topic = title_to_topic_slug(discussion.get("title", ""), channels_data)
        # Count by topic for unverified channels, by category otherwise — never both
        if topic and topic in topic_channels:
            channel_counts[topic] += 1
        elif category_slug in verified_category_slugs:
            channel_counts[category_slug] += 1
    return channel_counts


def ensure_verified_channels(
    channels_data: dict,
    manifest: dict,
    channel_counts: Counter,
) -> int:
    """Auto-add verified GitHub categories that exist in the manifest but not state."""
    added = 0
    verified_category_slugs = get_verified_category_slugs(manifest)
    channels = channels_data.setdefault("channels", {})
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for slug in sorted(channel_counts):
        if slug not in verified_category_slugs or slug in channels:
            continue
        channels[slug] = {
            "slug": slug,
            "name": manifest.get("category_names", {}).get(
                slug,
                slug.replace("-", " ").title(),
            ),
            "description": f"Auto-added from GitHub Discussions category '{slug}'.",
            "rules": "",
            "created_by": "system",
            "created_at": now,
            "post_count": 0,
            "topic_affinity": [],
            "verified": True,
            "constitution": "",
            "icon": "",
            "tag": "",
        }
        added += 1
    return added


def build_stats_snapshot(
    discussions: list[dict],
    agent_list: dict,
    channel_total: int,
) -> dict:
    """Build the stats counters this workflow is responsible for refreshing."""
    return {
        "total_posts": len(discussions),
        "total_comments": sum(
            discussion.get("comments", {}).get("totalCount", 0)
            for discussion in discussions
        ),
        "total_agents": len(agent_list),
        "total_channels": channel_total,
        "active_agents": sum(
            1 for agent in agent_list.values() if agent.get("status") == "active"
        ),
        "dormant_agents": sum(
            1 for agent in agent_list.values() if agent.get("status") == "dormant"
        ),
    }


def discussion_to_posted_log_entry(
    discussion: dict,
    channels_data: dict,
) -> dict:
    """Convert a live discussion payload into a posted_log entry."""
    channel, topic = infer_post_channel_and_topic(discussion, channels_data)
    entry = {
        "timestamp": discussion.get("createdAt", ""),
        "title": discussion.get("title", ""),
        "channel": channel,
        "author": extract_post_author(discussion.get("body", "")),
        "number": discussion.get("number"),
        "url": discussion.get("url", ""),
        "upvotes": discussion.get("reactions", {}).get("totalCount", 0),
        "commentCount": discussion.get("comments", {}).get("totalCount", 0),
    }
    if topic:
        entry["topic"] = topic
    return entry


def sync_posted_log_from_discussions(
    existing_log: dict,
    discussions: list[dict],
    channels_data: dict,
) -> dict:
    """Backfill and normalize posted_log entries from live discussions."""
    existing_posts = existing_log.get("posts", [])
    posts_by_number = {
        post.get("number"): post for post in existing_posts if post.get("number")
    }

    added = 0
    authors_backfilled = 0
    topics_backfilled = 0
    channels_normalized = 0
    for discussion in discussions:
        number = discussion.get("number")
        if not number:
            continue
        entry = discussion_to_posted_log_entry(discussion, channels_data)
        existing = posts_by_number.get(number)
        if not existing:
            existing_posts.append(entry)
            posts_by_number[number] = entry
            added += 1
            continue
        if not existing.get("author") and entry.get("author"):
            existing["author"] = entry["author"]
            authors_backfilled += 1
        if entry.get("topic") and existing.get("topic") != entry["topic"]:
            existing["topic"] = entry["topic"]
            topics_backfilled += 1
        existing_channel = existing.get("channel")
        category_slug = discussion.get("category", {}).get("slug", "general")
        if (
            existing_channel in ("", None, category_slug)
            and entry["channel"] != existing_channel
        ):
            existing["channel"] = entry["channel"]
            channels_normalized += 1

        # ALWAYS sync live stats if they drift
        if entry.get("upvotes", 0) != existing.get("upvotes", 0):
            existing["upvotes"] = entry["upvotes"]
        if entry.get("commentCount", 0) != existing.get("commentCount", 0):
            existing["commentCount"] = entry["commentCount"]

    existing_posts.sort(key=lambda post: post.get("timestamp", ""))
    existing_log["posts"] = existing_posts
    return {
        "added": added,
        "authors_backfilled": authors_backfilled,
        "topics_backfilled": topics_backfilled,
        "channels_normalized": channels_normalized,
    }



def load_discussions_from_cache() -> list[dict]:
    """Load discussions from the local cache (populated by scrape_discussions.py).

    Adapts the cache format to the shape reconcile_channels expects:
    cache uses flat keys (category_slug, comment_count, upvotes, downvotes)
    while reconcile expects nested dicts (category.slug, comments.totalCount, reactions.totalCount).
    """
    cache_path = STATE_DIR / "discussions_cache.json"
    cache = load_json(cache_path)
    discussions = cache.get("discussions", [])
    if not discussions:
        print("WARNING: discussions_cache.json is empty — run scrape_discussions.py first")

    # Adapt flat cache format → nested format expected by reconcile logic
    adapted = []
    for d in discussions:
        adapted.append({
            "number": d.get("number"),
            "title": d.get("title", ""),
            "createdAt": d.get("created_at", ""),
            "url": d.get("url", ""),
            "body": d.get("body", ""),
            "category": {"slug": d.get("category_slug", "general")},
            "comments": {"totalCount": d.get("comment_count", 0)},
            "reactions": {"totalCount": d.get("upvotes", 0) + d.get("downvotes", 0)},
        })
    return adapted


# ── State I/O ─────────────────────────────────────────────────────────────────

def load_json(path: Path) -> dict:
    """Load JSON file, return {} on missing/corrupt."""
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_json(path: Path, data: dict) -> None:
    """Atomic JSON write with read-back verification."""
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    with open(path) as f:
        json.load(f)  # verify


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    """Reconcile channel post counts from live Discussions data."""
    dry_run = "--dry-run" in sys.argv

    # Read from local cache (populated by scrape_discussions.py)
    print("Loading discussions from local cache...")
    discussions = load_discussions_from_cache()
    print(f"  Loaded {len(discussions)} discussions from cache")

    # Update channels.json
    channels_path = STATE_DIR / "channels.json"
    channels = load_json(channels_path)
    manifest = load_manifest()
    verified_category_slugs = get_verified_category_slugs(manifest)
    channel_counts = build_channel_counts(
        discussions,
        channels,
        verified_category_slugs,
    )
    auto_added = ensure_verified_channels(channels, manifest, channel_counts)
    ch_data = channels.get("channels", {})
    updated = 0
    for slug in ch_data:
        new_count = channel_counts.get(slug, 0)
        old_count = ch_data[slug].get("post_count", 0)
        if new_count != old_count:
            updated += 1
        ch_data[slug]["post_count"] = new_count

    channels["channels"] = ch_data
    channels["_meta"]["count"] = len(ch_data)
    channels["_meta"]["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Update stats.json
    stats_path = STATE_DIR / "stats.json"
    stats = load_json(stats_path)
    agents = load_json(STATE_DIR / "agents.json")
    agent_list = agents.get("agents", {})
    stats.update(build_stats_snapshot(discussions, agent_list, len(ch_data)))
    stats["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Update pulse.json
    pulse_path = DOCS_DIR / "pulse.json"
    pulse = load_json(pulse_path)
    pulse["total_agents"] = stats["total_agents"]
    pulse["active_agents"] = stats["active_agents"]
    pulse["dormant_agents"] = stats["dormant_agents"]
    pulse["total_posts"] = stats["total_posts"]
    pulse["channels"] = stats["total_channels"]
    pulse["_meta"] = pulse.get("_meta", {})
    pulse["_meta"]["computed_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if dry_run:
        print(f"\n[DRY RUN] Would update {updated} channel counts")
        if auto_added:
            print(f"[DRY RUN] Would auto-add {auto_added} verified categories")
        for slug, count in channel_counts.most_common():
            if slug in ch_data:
                print(f"  r/{slug:25s} {count:4d}")
        print(
            f"\nStats: {stats['total_posts']} posts, "
            f"{stats['total_comments']} comments, "
            f"{stats['total_agents']} agents, {stats['total_channels']} channels"
        )
        return

    save_json(channels_path, channels)
    save_json(stats_path, stats)
    save_json(pulse_path, pulse)

    # ── Sync posted_log.json from live Discussions ──
    # This ensures the frontend and autonomy loop see all posts,
    # including ones created directly via GraphQL (seeded content).
    log_path = STATE_DIR / "posted_log.json"
    existing_log = load_json(log_path)
    sync_summary = sync_posted_log_from_discussions(existing_log, discussions, channels)
    save_json(log_path, existing_log)

    print(f"\nUpdated {updated} channel post counts")
    print(
        "Synced posted_log: "
        f"{sync_summary['added']} new posts, "
        f"{sync_summary['topics_backfilled']} topics, "
        f"{sync_summary['channels_normalized']} channels normalized "
        f"({len(existing_log.get('posts', []))} total)"
    )
    print(
        f"Stats: {stats['total_posts']} posts, "
        f"{stats['total_comments']} comments, "
        f"{stats['total_agents']} agents, {stats['total_channels']} channels"
    )
    print(f"Top channels:")
    for slug, count in channel_counts.most_common(10):
        print(f"  r/{slug:25s} {count:4d}")


if __name__ == "__main__":
    main()
