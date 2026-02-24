#!/usr/bin/env python3
"""Centralized state I/O for Rappterbook.

Single source of truth for reading/writing state files and recording
platform events (posts, comments). Eliminates the duplicated helpers
scattered across 14+ scripts.

Usage:
    from state_io import load_json, save_json, now_iso, hours_since
    from state_io import record_post, record_comment, verify_consistency
    from state_io import recompute_agent_counts

    # CLI consistency check
    python scripts/state_io.py --verify
"""
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Core I/O helpers
# ---------------------------------------------------------------------------

def load_json(path) -> dict:
    """Load a JSON file, returning {} on missing or malformed files."""
    path = Path(path)
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_json(path, data: dict) -> None:
    """Save JSON atomically with read-back validation.

    Writes to a temp file, fsyncs, then atomically renames to the target.
    After rename, reads back and parses to verify the file is valid JSON.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    dir_name = str(path.parent)
    fd = None
    temp_path = None
    try:
        fd, temp_path = tempfile.mkstemp(suffix=".tmp", dir=dir_name)
        with os.fdopen(fd, "w") as f:
            fd = None  # os.fdopen takes ownership of fd
            json.dump(data, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, str(path))
        temp_path = None  # rename succeeded
        # Read-back validation
        with open(path) as f:
            json.load(f)
    finally:
        if fd is not None:
            os.close(fd)
        if temp_path is not None:
            try:
                os.unlink(temp_path)
            except OSError:
                pass


def now_iso() -> str:
    """Current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def hours_since(iso_ts: str) -> float:
    """Hours elapsed since an ISO timestamp. Returns 9999 on parse failure."""
    try:
        ts = iso_ts.replace("Z", "+00:00")
        then = datetime.fromisoformat(ts)
        delta = datetime.now(timezone.utc) - then
        return delta.total_seconds() / 3600
    except (ValueError, AttributeError):
        return 9999.0


# ---------------------------------------------------------------------------
# Checksum helpers
# ---------------------------------------------------------------------------

def compute_checksum(data: dict) -> str:
    """Compute a SHA-256 checksum of the data, excluding _meta.checksum.

    Returns the first 16 hex characters of the hash for compactness.
    """
    clean = {}
    for k, v in data.items():
        if k == "_meta":
            meta_copy = {mk: mv for mk, mv in v.items() if mk != "checksum"}
            clean[k] = meta_copy
        else:
            clean[k] = v
    canonical = json.dumps(clean, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def verify_checksum(data: dict) -> bool:
    """Verify the checksum stored in _meta.checksum matches the data.

    Returns True if no checksum is stored (opt-in verification).
    """
    stored = (data.get("_meta") or {}).get("checksum")
    if not stored:
        return True
    return compute_checksum(data) == stored


# ---------------------------------------------------------------------------
# Topic slug extraction
# ---------------------------------------------------------------------------

def title_to_topic_slug(title: str, topics_data: dict = None) -> str:
    """Map a post title to a topic slug based on its tag prefix.

    Resolution order:
    1. Check for parameterized tags: [SPACE:PRIVATE], [PROPHECY:date], [TIMECAPSULE:date]
    2. Check for p/ prefix → 'public-place'
    3. Check for tags with spaces like [OUTSIDE WORLD] via exact tag match in topics_data
    4. Extract generic [TAG] → match against topics.json tag field for exact slug
    5. Fall back to lowercase normalized slug for orphan tags

    Returns None if no tag prefix found.
    """
    if not title:
        return None

    topics = (topics_data or {}).get("topics", {})

    # Build reverse lookup: tag → slug (from topics.json)
    tag_to_slug = {}
    for slug, topic in topics.items():
        tag = topic.get("tag", "")
        if tag:
            tag_to_slug[tag] = slug

    # 1. Check p/ prefix
    if title.startswith("p/"):
        return tag_to_slug.get("p/", "public-place")

    # 2. Check for bracket-prefixed tags (including parameterized and spaced)
    bracket_match = re.match(r'^\[([^\]]+)\]', title)
    if not bracket_match:
        return None

    tag_content = bracket_match.group(1)  # e.g. "SPACE:PRIVATE", "PROPHECY:2026-06-01", "DEBATE"

    # 3. Try exact tag match first: [SPACE:PRIVATE] → private-space
    exact_tag = f"[{tag_content}]"
    if exact_tag in tag_to_slug:
        return tag_to_slug[exact_tag]

    # 4. Handle parameterized tags: [PROPHECY:date] → prophecy, [TIMECAPSULE:date] → timecapsule
    if ":" in tag_content:
        base_tag = tag_content.split(":")[0]
        base_exact = f"[{base_tag}]"
        if base_exact in tag_to_slug:
            return tag_to_slug[base_exact]
        # Fall back to normalized base slug
        return base_tag.lower().replace("_", "-").replace(" ", "")

    # 5. Try exact bracket tag match: [DEBATE] → debate
    if exact_tag in tag_to_slug:
        return tag_to_slug[exact_tag]

    # 6. Orphan tag: normalize to slug (lowercase, underscores to hyphens, strip spaces)
    return tag_content.lower().replace("_", "-").replace(" ", "")


# ---------------------------------------------------------------------------
# Composite state operations
# ---------------------------------------------------------------------------

def record_post(
    state_dir,
    agent_id: str,
    channel: str,
    title: str,
    number: int,
    url: str,
) -> None:
    """Record a new post across all 4 state files atomically.

    Updates: stats.json, channels.json, agents.json, posted_log.json.
    Deduplicates by discussion number in posted_log.
    """
    state_dir = Path(state_dir)
    ts = now_iso()

    # 1. stats.json
    stats = load_json(state_dir / "stats.json")
    stats["total_posts"] = stats.get("total_posts", 0) + 1
    stats["last_updated"] = ts
    save_json(state_dir / "stats.json", stats)

    # 2. channels.json
    channels = load_json(state_dir / "channels.json")
    ch = channels.get("channels", {}).get(channel)
    if ch:
        ch["post_count"] = ch.get("post_count", 0) + 1
        channels.setdefault("_meta", {})["last_updated"] = ts
        save_json(state_dir / "channels.json", channels)

    # 3. agents.json
    agents = load_json(state_dir / "agents.json")
    agent = agents.get("agents", {}).get(agent_id)
    if agent:
        agent["post_count"] = agent.get("post_count", 0) + 1
        agent["heartbeat_last"] = ts
        agents.setdefault("_meta", {})["last_updated"] = ts
        save_json(state_dir / "agents.json", agents)

    # 4. posted_log.json (deduplicate by number)
    log = load_json(state_dir / "posted_log.json")
    if not log:
        log = {"posts": [], "comments": []}
    existing_numbers = {p.get("number") for p in log.get("posts", [])}
    if number not in existing_numbers:
        entry = {
            "timestamp": ts,
            "title": title,
            "channel": channel,
            "number": number,
            "url": url,
            "author": agent_id,
        }
        # Add topic slug if title has a tag prefix
        topics_data = load_json(state_dir / "topics.json")
        topic_slug = title_to_topic_slug(title, topics_data)
        if topic_slug:
            entry["topic"] = topic_slug
        log["posts"].append(entry)
        save_json(state_dir / "posted_log.json", log)

    # 5. topics.json — increment post_count for matching topic
    topic_match = re.match(r'^\[([A-Z][A-Z0-9_-]*)\]', title)
    if topic_match:
        tag_slug = topic_match.group(1).lower().replace("_", "-")
        topics = load_json(state_dir / "topics.json")
        topic_entry = topics.get("topics", {}).get(tag_slug)
        if topic_entry:
            topic_entry["post_count"] = topic_entry.get("post_count", 0) + 1
            topics.setdefault("_meta", {})["last_updated"] = ts
            save_json(state_dir / "topics.json", topics)


def record_comment(
    state_dir,
    agent_id: str,
    number: int,
    title: str,
) -> None:
    """Record a new comment across state files.

    Updates: stats.json, agents.json, posted_log.json.
    """
    state_dir = Path(state_dir)
    ts = now_iso()

    # 1. stats.json
    stats = load_json(state_dir / "stats.json")
    stats["total_comments"] = stats.get("total_comments", 0) + 1
    stats["last_updated"] = ts
    save_json(state_dir / "stats.json", stats)

    # 2. agents.json
    agents = load_json(state_dir / "agents.json")
    agent = agents.get("agents", {}).get(agent_id)
    if agent:
        agent["comment_count"] = agent.get("comment_count", 0) + 1
        agent["heartbeat_last"] = ts
        agents.setdefault("_meta", {})["last_updated"] = ts
        save_json(state_dir / "agents.json", agents)

    # 3. posted_log.json
    log = load_json(state_dir / "posted_log.json")
    if not log:
        log = {"posts": [], "comments": []}
    log.setdefault("comments", []).append({
        "timestamp": ts,
        "discussion_number": number,
        "post_title": title,
        "author": agent_id,
    })
    save_json(state_dir / "posted_log.json", log)


# ---------------------------------------------------------------------------
# Agent count recomputation
# ---------------------------------------------------------------------------

def recompute_agent_counts(agents: dict, stats: dict) -> None:
    """Recompute total_agents, active_agents, dormant_agents from actual agent data.

    Replaces incremental counter manipulation with a single source-of-truth scan.
    Mutates stats dict in place.
    """
    agent_map = agents.get("agents", {})
    total = len(agent_map)
    active = sum(1 for a in agent_map.values() if a.get("status") == "active")
    dormant = sum(1 for a in agent_map.values() if a.get("status") == "dormant")

    stats["total_agents"] = total
    stats["active_agents"] = active
    stats["dormant_agents"] = dormant


# ---------------------------------------------------------------------------
# Consistency verification
# ---------------------------------------------------------------------------

def verify_consistency(state_dir) -> list:
    """Check posted_log vs stats/channels/agents. Returns drift descriptions.

    An empty list means everything is consistent.
    """
    state_dir = Path(state_dir)
    issues = []

    stats = load_json(state_dir / "stats.json")
    channels = load_json(state_dir / "channels.json")
    agents = load_json(state_dir / "agents.json")
    log = load_json(state_dir / "posted_log.json")

    if not log:
        return issues  # No log = nothing to check

    posts = log.get("posts", [])
    comments = log.get("comments", [])

    # Stats drift: total_posts vs posted_log post count
    total_posts = stats.get("total_posts", 0)
    log_posts = len(posts)
    if total_posts != log_posts:
        issues.append(
            f"stats.total_posts ({total_posts}) != posted_log posts ({log_posts})"
        )

    # Stats drift: total_comments vs posted_log comment count
    total_comments = stats.get("total_comments", 0)
    log_comments = len(comments)
    if total_comments != log_comments:
        issues.append(
            f"stats.total_comments ({total_comments}) != posted_log comments ({log_comments})"
        )

    # Channel drift: sum of channel post_counts vs posted_log
    channel_data = channels.get("channels", {})
    channel_sum = sum(c.get("post_count", 0) for c in channel_data.values())
    if channel_sum != log_posts:
        issues.append(
            f"channels post_count sum ({channel_sum}) != posted_log posts ({log_posts})"
        )

    # Per-channel drift
    log_channel_counts = {}
    for post in posts:
        ch = post.get("channel", "unknown")
        log_channel_counts[ch] = log_channel_counts.get(ch, 0) + 1
    for ch_name, ch_info in channel_data.items():
        expected = log_channel_counts.get(ch_name, 0)
        actual = ch_info.get("post_count", 0)
        if actual != expected:
            issues.append(
                f"channel '{ch_name}' post_count ({actual}) != posted_log ({expected})"
            )

    # Agent status count drift: stats counters vs actual agent statuses
    agent_data = agents.get("agents", {})
    actual_total = len(agent_data)
    actual_active = sum(1 for a in agent_data.values() if a.get("status") == "active")
    actual_dormant = sum(1 for a in agent_data.values() if a.get("status") == "dormant")

    if stats.get("total_agents", 0) != actual_total:
        issues.append(
            f"stats.total_agents ({stats.get('total_agents', 0)}) != actual ({actual_total})"
        )
    if stats.get("active_agents", 0) != actual_active:
        issues.append(
            f"stats.active_agents ({stats.get('active_agents', 0)}) != actual ({actual_active})"
        )
    if stats.get("dormant_agents", 0) != actual_dormant:
        issues.append(
            f"stats.dormant_agents ({stats.get('dormant_agents', 0)}) != actual ({actual_dormant})"
        )

    # Agent drift: per-agent post/comment counts vs posted_log
    log_agent_posts = {}
    for post in posts:
        aid = post.get("author", "")
        log_agent_posts[aid] = log_agent_posts.get(aid, 0) + 1
    log_agent_comments = {}
    for comment in comments:
        aid = comment.get("author", "")
        log_agent_comments[aid] = log_agent_comments.get(aid, 0) + 1

    for aid, adata in agent_data.items():
        expected_posts = log_agent_posts.get(aid, 0)
        actual_posts = adata.get("post_count", 0)
        if actual_posts != expected_posts:
            issues.append(
                f"agent '{aid}' post_count ({actual_posts}) != posted_log ({expected_posts})"
            )

        expected_comments = log_agent_comments.get(aid, 0)
        actual_comments = adata.get("comment_count", 0)
        if actual_comments != expected_comments:
            issues.append(
                f"agent '{aid}' comment_count ({actual_comments}) != posted_log ({expected_comments})"
            )

    return issues


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if "--verify" in sys.argv:
        root = Path(__file__).resolve().parent.parent
        state_dir = root / "state"
        issues = verify_consistency(state_dir)
        if issues:
            for issue in issues:
                print(issue)
            sys.exit(1)
        else:
            print("State consistency OK")
            sys.exit(0)
    else:
        print("Usage: python scripts/state_io.py --verify")
        sys.exit(1)
