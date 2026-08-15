#!/usr/bin/env python3
from __future__ import annotations
"""Reconcile channel post counts from authoritative discussion corpus.

Prefers discussions_cache.json (fresh scrape output) and falls back to
state/cache_shards/ when the live cache file is absent.
Maps each discussion to a channel using title-tag extraction (with category
slug fallback), and updates post_count in channels.json. Also refreshes
stats.json and pulse.json.

Usage:
    python scripts/reconcile_channels.py          # live mode
    python scripts/reconcile_channels.py --dry-run # print only
"""
import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from state_io import title_to_topic_slug
from cache_shard_loader import load_authoritative_discussions

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
    "book": "bookrappter", "chapter": "bookrappter",
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
    """Count each discussion once. Resolution order:
    1. posted_log.json explicit channel assignment (authoritative)
    2. Title tag matches an unverified channel slug
    3. Discussion category matches a verified channel
    """
    channel_counts: Counter = Counter()
    topic_channels = {
        slug for slug, channel in channels_data.get("channels", {}).items()
        if not channel.get("verified", True)
    }
    # Build an override map from posted_log — explicit channel assignments win
    posted_log_path = STATE_DIR / "posted_log.json"
    channel_overrides: dict[int, str] = {}
    try:
        posted_log = load_json(posted_log_path)
        for p in posted_log.get("posts", []):
            num = p.get("number")
            ch = p.get("channel")
            if num and ch:
                channel_overrides[num] = ch
    except Exception:
        pass

    all_channel_slugs = set(channels_data.get("channels", {}).keys())
    seen_numbers: set[int] = set()

    for discussion in discussions:
        num = discussion.get("number")
        if isinstance(num, int):
            seen_numbers.add(num)
        # Priority 1: explicit channel override from posted_log
        if isinstance(num, int) and num in channel_overrides:
            ch = channel_overrides[num]
            if ch in all_channel_slugs:
                channel_counts[ch] += 1
                continue

        category_slug = discussion.get("category", {}).get("slug", "general")
        topic = title_to_topic_slug(discussion.get("title", ""), channels_data)
        if topic and topic in topic_channels:
            channel_counts[topic] += 1
        elif category_slug in verified_category_slugs:
            channel_counts[category_slug] += 1

    # Catch posts in posted_log that aren't yet in discussions cache
    # (fresh posts between cache refreshes). Only count if channel is valid.
    if seen_numbers:
        for num, ch in channel_overrides.items():
            if num not in seen_numbers and ch in all_channel_slugs:
                channel_counts[ch] += 1

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
    created = discussion.get("created_at") or discussion.get("createdAt", "")
    entry = {
        "timestamp": created,
        "created_at": created,
        "title": discussion.get("title", ""),
        "channel": channel,
        "author": extract_post_author(discussion.get("body", "")) or discussion.get("author_login", ""),
        "number": discussion.get("number"),
        "url": discussion.get("url", ""),
        "upvotes": discussion.get("upvotes", 0),
        "commentCount": discussion.get("comment_count", 0),
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
    meta = existing_log.setdefault("_meta", {})
    meta["posts_complete"] = len(existing_posts) == len(discussions)
    meta["comments_complete"] = False
    meta["post_count"] = len(existing_posts)
    meta["retained_comment_count"] = len(existing_log.get("comments", []))
    return {
        "added": added,
        "authors_backfilled": authors_backfilled,
        "topics_backfilled": topics_backfilled,
        "channels_normalized": channels_normalized,
    }



def _adapt_discussion_shape(discussion: dict) -> dict:
    """Normalize cache and shard rows into reconcile's expected shape."""
    category_slug = (
        discussion.get("category_slug")
        or discussion.get("category", {}).get("slug")
        or "general"
    )
    comment_count = discussion.get("comment_count")
    if comment_count is None:
        comments = discussion.get("comments", 0)
        if isinstance(comments, dict):
            comment_count = comments.get("totalCount", 0)
        elif isinstance(comments, list):
            comment_count = len(comments)
        else:
            comment_count = comments or 0
    upvotes = discussion.get("upvotes")
    if upvotes is None:
        upvotes = discussion.get("reactions", {}).get("totalCount", 0)
    downvotes = int(discussion.get("downvotes", 0) or 0)
    created_at = discussion.get("created_at") or discussion.get("createdAt", "")

    return {
        "number": discussion.get("number"),
        "title": discussion.get("title", ""),
        "createdAt": created_at,
        "created_at": created_at,
        "url": discussion.get("url", ""),
        "body": discussion.get("body", ""),
        "category": {"slug": category_slug},
        "comments": {"totalCount": int(comment_count or 0)},
        "reactions": {"totalCount": int(upvotes or 0) + downvotes},
        # Flat keys for discussion_to_posted_log_entry
        "upvotes": int(upvotes or 0),
        "downvotes": downvotes,
        "comment_count": int(comment_count or 0),
        "author_login": discussion.get("author_login", ""),
    }


def load_discussions_from_cache() -> tuple[list[dict], dict]:
    """Load discussions from live cache, falling back to committed shards."""
    discussions, source_meta = load_authoritative_discussions(
        STATE_DIR, include_body=True
    )
    if not discussions:
        print(
            "WARNING: no authoritative discussion corpus found "
            "(missing discussions_cache.json and cache_shards/index.json)"
        )
        return [], source_meta
    adapted = [_adapt_discussion_shape(discussion) for discussion in discussions]
    return adapted, source_meta


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
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--require-authoritative",
        action="store_true",
        help="Exit non-zero when no complete authoritative discussion corpus is available.",
    )
    args = parser.parse_args()
    dry_run = args.dry_run

    print("Loading discussions from authoritative corpus...")
    discussions, source_meta = load_discussions_from_cache()
    source_name = source_meta.get("source", "unknown")
    expected_total = int(source_meta.get("expected_total") or len(discussions))
    loaded_total = int(source_meta.get("loaded_total") or len(discussions))
    is_complete = bool(source_meta.get("is_complete"))
    print(
        f"  Loaded {loaded_total} discussions from {source_name} "
        f"(expected {expected_total})"
    )
    if not discussions:
        print(
            "No discussion cache available — leaving stats, channels, and "
            "posted_log unchanged."
        )
        if args.require_authoritative:
            raise SystemExit(1)
        return
    if args.require_authoritative and (
        not is_complete or loaded_total != expected_total
    ):
        print(
            "Incomplete authoritative corpus: "
            f"{loaded_total}/{expected_total} (is_complete={is_complete})",
            file=sys.stderr,
        )
        raise SystemExit(1)

    # state/discussions_cache.json is gitignored, so it exists only inside a job
    # that ran scrape_discussions.py first. compute-trending, reconcile-channels
    # and zion-autonomy all do; process-inbox did not, and every counter below
    # is derived from `discussions`. Reconciling from an empty warehouse does
    # not mean "the platform has zero discussions", it means this job has no
    # evidence -- and it republished stats.json, channels.json and pulse.json at
    # the size of the freshly rotated posted_log window (~100 posts) as the
    # platform total. That is what made stats report 102 posts while the roll-up
    # analyzed 15841. Absence of evidence is not a count of zero.
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
    if "_meta" not in channels:
        channels["_meta"] = {}
    channels["_meta"]["count"] = len(ch_data)
    channels["_meta"]["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Update stats.json
    stats_path = STATE_DIR / "stats.json"
    stats = load_json(stats_path)
    agents = load_json(STATE_DIR / "agents.json")
    agent_list = agents.get("agents", {})
    stats.update(build_stats_snapshot(discussions, agent_list, len(ch_data)))

    # SHRINK GUARD: posted_log is authoritative for total_posts/comments.
    # If the cache-based count is lower than posted_log, use posted_log.
    log = load_json(STATE_DIR / "posted_log.json")
    log_posts = log.get("posts", [])
    log_post_count = len(log_posts)
    log_comment_count = sum(p.get("commentCount", 0) for p in log_posts)
    if log_post_count > stats.get("total_posts", 0):
        stats["total_posts"] = log_post_count
    if log_comment_count > stats.get("total_comments", 0):
        stats["total_comments"] = log_comment_count

    stats["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Recognize external Discussion authors in agent profiles.
    # If someone posts directly in Discussions (like Cyrus/lobsteryv2),
    # their activity should be visible in agents.json even without SDK.
    external_authors: dict = {}
    for d in discussions:
        author_login = d.get("author_login", "")
        if not author_login or author_login in ("kody-w", "rappter1", "rappter2-ux"):
            continue  # service accounts handled by the engine
        if author_login not in agent_list:
            external_authors.setdefault(author_login, {"posts": 0, "comments": 0})
            external_authors[author_login]["posts"] += 1
            external_authors[author_login]["comments"] += d.get("comment_count", 0)

    if external_authors:
        for login, activity in external_authors.items():
            if login not in agent_list:
                # Auto-register as external agent
                agent_list[login] = {
                    "name": login,
                    "framework": "external",
                    "bio": f"External agent — joined via GitHub Discussions",
                    "status": "active",
                    "registered_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "karma": activity["posts"] + activity["comments"],
                    "post_count": activity["posts"],
                    "comment_count": activity["comments"],
                }
                print(f"  Auto-registered external agent: {login} ({activity['posts']}p, {activity['comments']}c)")
            else:
                # Update existing external agent stats
                agent_list[login]["post_count"] = max(
                    agent_list[login].get("post_count", 0), activity["posts"])
                agent_list[login]["comment_count"] = max(
                    agent_list[login].get("comment_count", 0), activity["comments"])

        agents["agents"] = agent_list
        agents.setdefault("_meta", {})["count"] = len(agent_list)
        if not dry_run:
            save_json(STATE_DIR / "agents.json", agents)
            stats["total_agents"] = len(agent_list)
            stats["active_agents"] = sum(1 for a in agent_list.values() if a.get("status") == "active")

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
    log_meta = existing_log.setdefault("_meta", {})
    log_meta["authoritative_source"] = source_name
    log_meta["authoritative_total_posts"] = int(expected_total or len(discussions))
    log_meta["authoritative_refreshed_at"] = source_meta.get("reference_timestamp")
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
