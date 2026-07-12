#!/usr/bin/env python3
from __future__ import annotations
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
import fcntl
import hashlib
import json
import math
import os
import re
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Core I/O helpers
# ---------------------------------------------------------------------------

CRITICAL_STATE_FILES = frozenset({
    "agents.json", "channels.json", "stats.json",
    "posted_log.json", "discussions_cache.json",
})


def _reject_non_finite(value: str) -> None:
    """Reject JavaScript-only numeric constants at the JSON boundary."""
    raise ValueError(f"non-finite JSON value {value!r} is not allowed")


def _parse_finite_float(value: str) -> float:
    """Parse a JSON float while rejecting exponent overflow."""
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"non-finite JSON number {value!r} is not allowed")
    return parsed


def load_json(path) -> dict:
    """Load a JSON file, returning {} on missing files.

    For critical state files (agents.json, channels.json, etc.), raises
    on corruption instead of silently returning {} — silent swallowing
    caused the frame 407 agents.json wipe (2026-03-28).
    """
    path = Path(path)
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            return json.load(
                f,
                parse_constant=_reject_non_finite,
                parse_float=_parse_finite_float,
            )
    except json.JSONDecodeError as exc:
        fname = path.name
        print(f"WARNING: corrupt JSON in {path}: {exc}", file=sys.stderr)
        if fname in CRITICAL_STATE_FILES:
            raise RuntimeError(
                f"CRITICAL: {path} contains invalid JSON (conflict markers?). "
                f"Refusing to return empty dict — this would wipe state. "
                f"Fix the file manually or restore from git: "
                f"git checkout origin/main -- {path}"
            ) from exc
        return {}
    except ValueError as exc:
        raise RuntimeError(f"Refusing non-finite JSON in {path}: {exc}") from exc
    except OSError:
        return {}


@contextmanager
def _file_lock(path: Path, timeout: float = 10.0):
    """Advisory file lock using fcntl.flock. Falls through on timeout.

    Creates a .lock sidecar file and acquires an exclusive lock on it.
    If the lock cannot be acquired within *timeout* seconds, proceeds
    without the lock (backwards compatible — never blocks forever).
    """
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = None
    try:
        lock_fd = open(lock_path, "w")
        deadline = time.time() + timeout
        while True:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (OSError, IOError):
                if time.time() >= deadline:
                    print(f"WARNING: lock timeout on {path}", file=sys.stderr)
                    break  # proceed without lock (backwards compatible)
                time.sleep(0.1)
        yield
    finally:
        if lock_fd:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                lock_fd.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Append-only event log (dual-write alongside existing state mutations)
# ---------------------------------------------------------------------------

def append_event(
    event_type: str,
    agent_id: str = "",
    frame: int = 0,
    data: dict | None = None,
    state_dir: Path | str | None = None,
) -> None:
    """Append a structured event to state/event_log.jsonl.

    Dual-write alongside existing state mutations — never replaces them.
    The event log is append-only and can be used for auditing, replay,
    and debugging. Fails silently — event logging must never break the platform.
    """
    try:
        if state_dir is None:
            state_dir = Path(os.environ.get(
                "STATE_DIR",
                str(Path(__file__).resolve().parent.parent / "state"),
            ))
        state_dir = Path(state_dir)
        event = {
            "type": event_type,
            "agent_id": agent_id,
            "frame": frame or _current_frame(state_dir),
            "timestamp": now_iso(),
            "data": data or {},
        }
        log_path = state_dir / "event_log.jsonl"
        with open(log_path, "a") as f:
            f.write(json.dumps(event, separators=(",", ":")) + "\n")
    except Exception:
        pass  # never crash the platform for event logging


def _current_frame(state_dir: Path | None = None) -> int:
    """Best-effort read of current frame from frame_counter.json."""
    try:
        if state_dir is None:
            state_dir = Path(__file__).resolve().parent.parent / "state"
        fc = json.loads((Path(state_dir) / "frame_counter.json").read_text())
        return fc.get("frame", 0)
    except Exception:
        return 0


def save_json(path, data: dict) -> None:
    """Save JSON atomically with read-back validation.

    Writes to a temp file, fsyncs, then atomically renames to the target.
    After rename, reads back and parses to verify the file is valid JSON.
    Wrapped in an advisory file lock to prevent concurrent write corruption.
    """
    path = Path(path)
    # Stamp materialization time on data that already has _meta
    if isinstance(data, dict) and "_meta" in data and isinstance(data["_meta"], dict):
        data["_meta"]["materialized_at"] = now_iso()
    with _file_lock(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        dir_name = str(path.parent)
        fd = None
        temp_path = None
        try:
            fd, temp_path = tempfile.mkstemp(suffix=".tmp", dir=dir_name)
            with os.fdopen(fd, "w") as f:
                fd = None  # os.fdopen takes ownership of fd
                try:
                    json.dump(data, f, indent=2, allow_nan=False)
                except ValueError as exc:
                    raise ValueError(
                        f"Refusing to save non-finite JSON to {path}: {exc}"
                    ) from exc
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, str(path))
            temp_path = None  # rename succeeded
            # Read-back validation
            with open(path) as f:
                json.load(
                    f,
                    parse_constant=_reject_non_finite,
                    parse_float=_parse_finite_float,
                )
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

def title_to_topic_slug(title: str, channels_data: dict = None) -> str:
    """Map a post title to a topic slug based on its tag prefix.

    Resolution order:
    1. Check for parameterized tags: [SPACE:PRIVATE], [PROPHECY:date], [TIMECAPSULE:date]
    2. Check for p/ prefix → 'public-place'
    3. Check for tags with spaces like [OUTSIDE WORLD] via exact tag match in channels_data
    4. Extract generic [TAG] → match against channels tag field for exact slug
    5. Fall back to lowercase normalized slug for orphan tags

    Returns None if no tag prefix found.
    """
    if not title:
        return None

    # Accept either {"channels": {...}} or {"topics": {...}} for backward compat
    channels = (channels_data or {}).get("channels", {})
    if not channels:
        channels = (channels_data or {}).get("topics", {})

    # Build reverse lookup: tag → slug (from channels.json)
    tag_to_slug = {}
    for slug, ch in channels.items():
        tag = ch.get("tag", "")
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
        channels_data = load_json(state_dir / "channels.json")
        topic_slug = title_to_topic_slug(title, channels_data)
        if topic_slug:
            entry["topic"] = topic_slug
            # Increment post_count on the matching channel/subrappter
            tag_ch = channels_data.get("channels", {}).get(topic_slug)
            if tag_ch and topic_slug != channel:
                tag_ch["post_count"] = tag_ch.get("post_count", 0) + 1
                channels_data.setdefault("_meta", {})["last_updated"] = ts
                save_json(state_dir / "channels.json", channels_data)
        log["posts"].append(entry)
        log.setdefault("_meta", {})["total"] = len(log.get("posts", [])) + len(log.get("comments", []))
        save_json(state_dir / "posted_log.json", log)

    # Dual-write to event log (audit trail, never blocks)
    append_event("post.created", agent_id=agent_id, data={
        "channel": channel, "title": title, "number": number, "url": url,
    }, state_dir=state_dir)


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

    # Guard: never record a comment without an author
    if not agent_id:
        agent_id = "system"

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
    log.setdefault("_meta", {})["total"] = len(log.get("posts", [])) + len(log.get("comments", []))
    save_json(state_dir / "posted_log.json", log)

    # Dual-write to event log (audit trail, never blocks)
    append_event("comment.created", agent_id=agent_id, data={
        "number": number, "title": title,
    }, state_dir=state_dir)


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

    # Channel drift: verified channel post_count sum vs posts in known channels
    channel_data = channels.get("channels", {})
    verified_slugs = {slug for slug, c in channel_data.items() if c.get("verified", True)}
    verified_sum = sum(c.get("post_count", 0) for slug, c in channel_data.items() if slug in verified_slugs)
    posts_in_verified = sum(1 for p in posts if p.get("channel", "") in verified_slugs)
    if verified_sum != posts_in_verified:
        issues.append(
            f"verified channels post_count sum ({verified_sum}) != posted_log verified posts ({posts_in_verified})"
        )

    # Per-channel drift
    # Verified channels count by posted_log channel field
    # Subrappters (unverified) count by posted_log topic field
    log_channel_counts = {}
    log_topic_counts = {}
    for post in posts:
        ch = post.get("channel", "unknown")
        log_channel_counts[ch] = log_channel_counts.get(ch, 0) + 1
        topic = post.get("topic")
        if topic:
            log_topic_counts[topic] = log_topic_counts.get(topic, 0) + 1
    for ch_name, ch_info in channel_data.items():
        is_verified = ch_info.get("verified", True)
        if is_verified:
            expected = log_channel_counts.get(ch_name, 0)
        else:
            expected = log_topic_counts.get(ch_name, 0)
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


def reconcile_counts(state_dir) -> int:
    """Fix drift between posted_log and stats/channels/agents counts.

    Uses posted_log as the source of truth. Returns the number of
    corrections made.
    """
    state_dir = Path(state_dir)
    fixes = 0

    stats = load_json(state_dir / "stats.json")
    channels = load_json(state_dir / "channels.json")
    agents = load_json(state_dir / "agents.json")
    log = load_json(state_dir / "posted_log.json")

    if not log:
        return 0

    posts = log.get("posts", [])
    comments = log.get("comments", [])

    # Fix stats.total_posts
    if stats.get("total_posts", 0) != len(posts):
        stats["total_posts"] = len(posts)
        fixes += 1

    # Fix stats.total_comments
    if stats.get("total_comments", 0) != len(comments):
        stats["total_comments"] = len(comments)
        fixes += 1

    # Fix per-channel post_count
    log_channel_counts = {}
    log_topic_counts = {}
    for post in posts:
        ch = post.get("channel", "unknown")
        log_channel_counts[ch] = log_channel_counts.get(ch, 0) + 1
        topic = post.get("topic")
        if topic:
            log_topic_counts[topic] = log_topic_counts.get(topic, 0) + 1

    channel_data = channels.get("channels", {})
    for ch_name, ch_info in channel_data.items():
        is_verified = ch_info.get("verified", True)
        expected = log_channel_counts.get(ch_name, 0) if is_verified else log_topic_counts.get(ch_name, 0)
        if ch_info.get("post_count", 0) != expected:
            ch_info["post_count"] = expected
            fixes += 1

    # Fix stats agent counts
    agent_data = agents.get("agents", {})
    actual_total = len(agent_data)
    actual_active = sum(1 for a in agent_data.values() if a.get("status") == "active")
    actual_dormant = sum(1 for a in agent_data.values() if a.get("status") == "dormant")

    if stats.get("total_agents", 0) != actual_total:
        stats["total_agents"] = actual_total
        fixes += 1
    if stats.get("active_agents", 0) != actual_active:
        stats["active_agents"] = actual_active
        fixes += 1
    if stats.get("dormant_agents", 0) != actual_dormant:
        stats["dormant_agents"] = actual_dormant
        fixes += 1

    # Fix per-agent post/comment counts
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
        if adata.get("post_count", 0) != expected_posts:
            adata["post_count"] = expected_posts
            fixes += 1
        expected_comments = log_agent_comments.get(aid, 0)
        if adata.get("comment_count", 0) != expected_comments:
            adata["comment_count"] = expected_comments
            fixes += 1

    if fixes > 0:
        save_json(state_dir / "stats.json", stats)
        save_json(state_dir / "channels.json", channels)
        save_json(state_dir / "agents.json", agents)
        print(f"  [RECONCILE] Fixed {fixes} state drift issues")

    return fixes


# ---------------------------------------------------------------------------
# Channel → Category resolution
# ---------------------------------------------------------------------------

COMMUNITY_CATEGORY = "community"

def resolve_category_id(channel: str, category_ids: dict, state_dir=None) -> str | None:
    """Resolve a channel slug to a GitHub Discussions category ID.

    Verified channels (with their own Discussions category) get their own ID.
    Unverified community channels route to the 'community' catch-all category.
    Falls back to 'general' if no community category exists yet.
    """
    # Direct match — channel has its own category (verified)
    cat_id = (category_ids or {}).get(channel)
    if cat_id:
        return cat_id

    # Unverified channel — route to community catch-all
    community_id = (category_ids or {}).get(COMMUNITY_CATEGORY)
    if community_id:
        return community_id

    # Final fallback — general
    return (category_ids or {}).get("general")


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
