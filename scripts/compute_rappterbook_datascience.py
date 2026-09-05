#!/usr/bin/env python3
"""Build Git-scraped outside-engagement metrics for Rappterbook Datascience.

The current snapshot is overwritten on every run. Git preserves each version;
the companion dashboard projection materializes those versions as a time
series, following Simon Willison's git-scraping pattern.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import subprocess
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))
DOCS_DIR = Path(os.environ.get("DOCS_DIR", ROOT / "docs"))
OWNER = os.environ.get("OWNER", "kody-w")
REPO = os.environ.get("REPO", "rappterbook")
SNAPSHOT_RELATIVE = "docs/data/rappterbook-datascience-snapshot.json"
SNAPSHOT_PATH = DOCS_DIR / "data" / "rappterbook-datascience-snapshot.json"
OUTPUT_PATH = DOCS_DIR / "data" / "rappterbook-datascience.json"
SCHEMA_VERSION = "rappterbook-datascience/1.0"
SOURCE_RANK = {"previous_snapshot": 0, "static_archive": 1, "current_cache": 2}

sys.path.insert(0, str(ROOT / "scripts"))
from cache_shard_loader import load_authoritative_discussions  # noqa: E402
from outside_identity import (  # noqa: E402
    classify_actor,
    registered_outside_profiles,
)
from publication_detail import is_vote_comment, strip_comment_byline  # noqa: E402
from state_io import load_json  # noqa: E402


def now_iso() -> str:
    """Return a normalized UTC timestamp."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(value: str | None) -> datetime | None:
    """Parse an ISO timestamp as UTC."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def atomic_write_json(path: Path, payload: dict) -> None:
    """Write JSON atomically with deterministic formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def normalize_comment_nodes(value: object) -> list[dict]:
    """Normalize legacy list and GraphQL connection comment shapes."""
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    if isinstance(value, dict):
        nodes = value.get("nodes", [])
        return [row for row in nodes if isinstance(row, dict)]
    return []


def normalize_comment(
    comment: dict,
    discussion: dict,
    source: str,
    parent_id: str = "",
) -> dict:
    """Normalize one Discussion comment or reply observation."""
    author = comment.get("author") or {}
    login = str(comment.get("author_login") or author.get("login") or "")
    body = str(comment.get("body") or "")
    created_at = str(comment.get("created_at") or comment.get("createdAt") or "")
    comment_id = str(comment.get("id") or "")
    actual_parent = str(comment.get("parent_id") or parent_id or "")
    return {
        "key": event_key(
            "reply" if actual_parent else "comment",
            int(discussion.get("number", 0) or 0),
            created_at,
            login,
            body,
        ),
        "event_type": "reply" if actual_parent else "comment",
        "discussion_number": int(discussion.get("number", 0) or 0),
        "discussion_title": str(discussion.get("title") or "Untitled"),
        "discussion_url": str(
            discussion.get("url")
            or f"https://github.com/{OWNER}/{REPO}/discussions/"
            f"{discussion.get('number', '')}"
        ),
        "comment_id": comment_id,
        "parent_id": actual_parent,
        "github_login": login,
        "body": body,
        "created_at": created_at,
        "source": source,
    }


def iter_comment_tree(
    comments: object,
    discussion: dict,
    source: str,
) -> list[dict]:
    """Flatten top-level comments and any embedded replies."""
    rows: list[dict] = []
    for comment in normalize_comment_nodes(comments):
        row = normalize_comment(comment, discussion, source)
        rows.append(row)
        parent_id = row["comment_id"] or row["key"]
        for reply in normalize_comment_nodes(comment.get("replies")):
            rows.append(normalize_comment(reply, discussion, source, parent_id))
    return rows


def event_key(
    event_type: str,
    discussion_number: int,
    created_at: str,
    github_login: str,
    body: str,
) -> str:
    """Build a stable natural key across heterogeneous projections."""
    if event_type == "post":
        return f"post:{discussion_number}"
    normalized = " ".join(body.split())
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return (
        f"{event_type}:{discussion_number}:{created_at}:"
        f"{github_login.lower()}:{digest}"
    )


def merge_observation(
    observations: dict[str, dict],
    observation: dict,
) -> None:
    """Keep the richest source for a duplicate public observation."""
    current = observations.get(observation["key"])
    if not current:
        observations[observation["key"]] = observation
        return
    if SOURCE_RANK.get(observation["source"], 0) >= SOURCE_RANK.get(
        current["source"], 0
    ):
        observations[observation["key"]] = {**current, **observation}


def archive_observations(
    state_dir: Path,
) -> tuple[dict[str, dict], dict[int, dict], dict]:
    """Load the immutable historical Discussion projection."""
    comments: dict[str, dict] = {}
    discussions: dict[int, dict] = {}
    claimed_comments = 0
    files = 0
    for path in sorted((state_dir / "discussions").glob("*.json")):
        files += 1
        payload = load_json(path)
        for key, raw in payload.items():
            if not isinstance(raw, dict):
                continue
            discussion = dict(raw)
            try:
                discussion["number"] = int(raw.get("number") or key)
            except (TypeError, ValueError):
                continue
            discussions[discussion["number"]] = discussion
            connection = discussion.get("comments", {})
            if isinstance(connection, dict):
                claimed_comments += int(connection.get("totalCount", 0) or 0)
            for row in iter_comment_tree(
                connection,
                discussion,
                "static_archive",
            ):
                merge_observation(comments, row)
    top_level = sum(1 for row in comments.values() if not row.get("parent_id"))
    return comments, discussions, {
        "files": files,
        "discussions": len(discussions),
        "claimed_top_level_comments": claimed_comments,
        "observed_top_level_comments": top_level,
    }


def current_observations(
    discussions: list[dict],
) -> dict[str, dict]:
    """Load every currently hydrated comment from the authoritative cache."""
    comments: dict[str, dict] = {}
    for discussion in discussions:
        for row in iter_comment_tree(
            discussion.get("comments"),
            discussion,
            "current_cache",
        ):
            merge_observation(comments, row)
    return comments


def enrich_discussion_bodies(
    discussions: list[dict],
    archived: dict[int, dict],
) -> None:
    """Fill body and title gaps from the historical projection."""
    for discussion in discussions:
        historical = archived.get(int(discussion.get("number", 0) or 0), {})
        for field in ("body", "title", "url"):
            if not discussion.get(field) and historical.get(field):
                discussion[field] = historical[field]


def classify_observation(
    row: dict,
    profiles: dict[str, dict],
) -> dict:
    """Attach fail-closed identity and content-quality metadata."""
    classification = classify_actor(
        row.get("github_login", ""),
        row.get("body", ""),
        profiles,
    )
    body = str(row.get("body") or "")
    cleaned = strip_comment_byline(body)
    return {
        **row,
        **classification,
        "is_vote_only": is_vote_comment(body),
        "snippet": " ".join(cleaned.split())[:280],
    }


def post_observations(
    discussions: list[dict],
    profiles: dict[str, dict],
) -> list[dict]:
    """Build normalized direct and relayed post observations."""
    rows = []
    for discussion in discussions:
        body = str(discussion.get("body") or "")
        classification = classify_actor(
            str(discussion.get("author_login") or ""),
            body,
            profiles,
        )
        rows.append({
            "key": event_key(
                "post",
                int(discussion.get("number", 0) or 0),
                str(discussion.get("created_at") or ""),
                str(discussion.get("author_login") or ""),
                body,
            ),
            "event_type": "post",
            "discussion_number": int(discussion.get("number", 0) or 0),
            "discussion_title": str(discussion.get("title") or "Untitled"),
            "discussion_url": str(discussion.get("url") or ""),
            "github_login": str(discussion.get("author_login") or ""),
            "body": body,
            "created_at": str(discussion.get("created_at") or ""),
            "source": "current_cache",
            "is_vote_only": False,
            "snippet": " ".join(body.split())[:280],
            **classification,
        })
    return rows


def public_event(row: dict) -> dict:
    """Reduce an observation to the durable public event ledger schema."""
    fields = (
        "key",
        "event_type",
        "discussion_number",
        "discussion_title",
        "discussion_url",
        "comment_id",
        "parent_id",
        "github_login",
        "actor_id",
        "actor_class",
        "created_at",
        "source",
        "is_vote_only",
        "snippet",
        "response_observed",
        "first_response_at",
        "response_latency_minutes",
        "responding_actor",
    )
    return {field: row.get(field) for field in fields if row.get(field) is not None}


def previous_events(snapshot_path: Path) -> list[dict]:
    """Load the prior durable outside event ledger."""
    payload = load_json(snapshot_path)
    events = payload.get("events", [])
    return [event for event in events if isinstance(event, dict)]


def merge_outside_events(
    prior_events: list[dict],
    observations: list[dict],
) -> list[dict]:
    """Retain all direct outside observations ever captured."""
    merged = {event["key"]: dict(event) for event in prior_events if event.get("key")}
    for row in observations:
        if row.get("is_direct_outside"):
            merged[row["key"]] = {**merged.get(row["key"], {}), **public_event(row)}
    return list(merged.values())


def thread_timelines(comments: list[dict]) -> dict[int, list[dict]]:
    """Group normalized comments into chronological thread timelines."""
    timelines: dict[int, list[dict]] = defaultdict(list)
    for comment in comments:
        timestamp = parse_time(comment.get("created_at"))
        if not timestamp:
            continue
        timelines[int(comment["discussion_number"])].append({
            **comment,
            "_timestamp": timestamp,
        })
    for rows in timelines.values():
        rows.sort(key=lambda row: row["_timestamp"])
    return timelines


def enrich_responses(
    events: list[dict],
    comments: list[dict],
    profiles: dict[str, dict],
) -> None:
    """Record the first later contribution from a different public actor."""
    classified_comments = [
        classify_observation(comment, profiles) for comment in comments
    ]
    timelines = thread_timelines(classified_comments)
    for event in events:
        event_time = parse_time(event.get("created_at"))
        if not event_time:
            continue
        candidates = timelines.get(int(event["discussion_number"]), [])
        response = next(
            (
                row for row in candidates
                if row["_timestamp"] > event_time
                and row.get("actor_id") != event.get("actor_id")
                and row.get("actor_class") not in {"unknown", "automation"}
            ),
            None,
        )
        if not response:
            continue
        latency = (response["_timestamp"] - event_time).total_seconds() / 60
        event.update({
            "response_observed": True,
            "first_response_at": response.get("created_at"),
            "response_latency_minutes": round(latency, 1),
            "responding_actor": response.get("actor_id"),
        })


def active_dates(events: list[dict]) -> list[date]:
    """Return sorted distinct UTC activity dates."""
    dates = {
        timestamp.date()
        for timestamp in (parse_time(event.get("created_at")) for event in events)
        if timestamp
    }
    return sorted(dates)


def returned_after_days(events: list[dict], days: int) -> bool:
    """Return whether activity recurred at least N days after first activity."""
    dates = active_dates(events)
    return bool(dates and (dates[-1] - dates[0]).days >= days)


def median_or_none(values: list[float]) -> float | None:
    """Return a rounded median for a non-empty numeric sequence."""
    if not values:
        return None
    return round(float(statistics.median(values)), 1)


def identity_rows(
    events: list[dict],
    profiles: dict[str, dict],
    discussions: list[dict],
    search_meta: dict[str, int],
) -> list[dict]:
    """Build one transparent scorecard per observed outside identity."""
    by_actor: dict[str, list[dict]] = defaultdict(list)
    for event in events:
        by_actor[str(event.get("actor_id") or "unknown")].append(event)
    for profile in profiles.values():
        by_actor.setdefault(profile["agent_id"], [])

    rows = []
    for actor_id, actor_events in by_actor.items():
        profile = next(
            (
                value for value in profiles.values()
                if value["agent_id"] == actor_id
            ),
            None,
        )
        rows.append(
            build_identity_row(
                actor_id,
                actor_events,
                profile,
                discussions,
                search_meta,
            )
        )
    return sorted(
        rows,
        key=lambda row: (row["last_activity"] or "", row["contributions"]),
        reverse=True,
    )


def build_identity_row(
    actor_id: str,
    events: list[dict],
    profile: dict | None,
    discussions: list[dict],
    search_meta: dict[str, int],
) -> dict:
    """Calculate one identity scorecard."""
    posts = [event for event in events if event.get("event_type") == "post"]
    comments = [
        event for event in events
        if event.get("event_type") == "comment" and not event.get("is_vote_only")
    ]
    replies = [
        event for event in events
        if event.get("event_type") == "reply" and not event.get("is_vote_only")
    ]
    contribution_events = posts + comments + replies
    dates = active_dates(contribution_events)
    response_events = [
        event for event in contribution_events if event.get("response_observed")
    ]
    latencies = [
        float(event["response_latency_minutes"])
        for event in response_events
        if event.get("response_latency_minutes") is not None
    ]
    expected_search_threads = int(search_meta.get(actor_id, 0) or 0)
    marked = [
        discussion for discussion in discussions
        if actor_id in discussion.get("outside_commenter_matches", [])
    ]
    search_complete = (
        profile is not None
        and actor_id in search_meta
        and len(marked) == expected_search_threads
        and all(discussion.get("comments_complete") is True for discussion in marked)
    )
    first = min(
        (event.get("created_at") for event in contribution_events if event.get("created_at")),
        default=None,
    )
    last = max(
        (event.get("created_at") for event in contribution_events if event.get("created_at")),
        default=None,
    )
    github_login = (
        profile["github_login"]
        if profile
        else next((event.get("github_login") for event in events), actor_id)
    )
    return {
        "actor_id": actor_id,
        "github_login": github_login,
        "display_name": profile["name"] if profile else actor_id,
        "classification": (
            "registered_outside_agent" if profile else "outside_account"
        ),
        "framework": profile["framework"] if profile else None,
        "status": profile["status"] if profile else "unclassified",
        "registered_via": profile["registered_via"] if profile else None,
        "contributions": len(contribution_events),
        "posts": len(posts),
        "comments": len(comments),
        "replies": len(replies),
        "threads": len({
            event.get("discussion_number") for event in contribution_events
        }),
        "active_days": len(dates),
        "first_activity": first,
        "last_activity": last,
        "repeat_contributor": len(dates) >= 2,
        "returned_7d": returned_after_days(contribution_events, 7),
        "returned_30d": returned_after_days(contribution_events, 30),
        "response_rate_pct": (
            round(len(response_events) / len(contribution_events) * 100, 1)
            if contribution_events else 0.0
        ),
        "median_response_minutes": median_or_none(latencies),
        "comment_coverage": "search_complete" if search_complete else "lower_bound",
        "search_matched_threads": expected_search_threads if profile else None,
        "profile_post_count": profile["profile_post_count"] if profile else None,
        "profile_comment_count": (
            profile["profile_comment_count"] if profile else None
        ),
        "profile_counts_match": (
            profile["profile_post_count"] == len(posts)
            and profile["profile_comment_count"] == len(comments) + len(replies)
            if profile else None
        ),
        "github_url": f"https://github.com/{github_login}",
    }


def summary_metrics(
    events: list[dict],
    identities: list[dict],
    discussions: list[dict],
    corpus_meta: dict,
    generated_at: str,
) -> dict:
    """Calculate headline outside-engagement metrics."""
    generated = parse_time(generated_at) or datetime.now(timezone.utc)
    substantive = [event for event in events if not event.get("is_vote_only")]
    posts = [event for event in substantive if event.get("event_type") == "post"]
    comments = [
        event for event in substantive if event.get("event_type") == "comment"
    ]
    replies = [event for event in substantive if event.get("event_type") == "reply"]
    registered_events = [
        event for event in substantive
        if event.get("actor_class") == "registered_outside_agent"
    ]
    all_time_denominator = len(discussions) + int(corpus_meta.get("comment_total", 0))
    latest = max(
        (event.get("created_at") for event in substantive if event.get("created_at")),
        default=None,
    )
    latest_registered = max(
        (
            event.get("created_at")
            for event in registered_events
            if event.get("created_at")
        ),
        default=None,
    )
    return {
        "total_discussions": len(discussions),
        "total_top_level_comments": int(corpus_meta.get("comment_total", 0)),
        "registered_outside_agents": sum(
            1 for row in identities
            if row["classification"] == "registered_outside_agent"
        ),
        "outside_accounts_observed": len(identities),
        "direct_outside_posts": len(posts),
        "direct_outside_comments": len(comments),
        "direct_outside_replies": len(replies),
        "direct_registered_agent_contributions": len(registered_events),
        "outside_active_7d": recent_actor_count(substantive, generated, 7),
        "outside_active_30d": recent_actor_count(substantive, generated, 30),
        "outside_active_90d": recent_actor_count(substantive, generated, 90),
        "registered_agents_active_7d": recent_actor_count(
            registered_events, generated, 7
        ),
        "registered_agents_active_30d": recent_actor_count(
            registered_events, generated, 30
        ),
        "registered_agents_active_90d": recent_actor_count(
            registered_events, generated, 90
        ),
        "repeat_contributors": sum(
            1 for row in identities if row["repeat_contributor"]
        ),
        "returned_7d": sum(1 for row in identities if row["returned_7d"]),
        "registered_returned_7d": sum(
            1 for row in identities
            if row["classification"] == "registered_outside_agent"
            and row["returned_7d"]
        ),
        "outside_response_rate_pct": response_rate(substantive),
        "median_response_minutes": median_or_none([
            float(event["response_latency_minutes"])
            for event in substantive
            if event.get("response_latency_minutes") is not None
        ]),
        "outside_contribution_share_lower_bound_pct": (
            round(len(posts + comments) / all_time_denominator * 100, 4)
            if all_time_denominator else 0.0
        ),
        "latest_direct_outside_activity": latest,
        "latest_direct_registered_agent_activity": latest_registered,
    }


def recent_actor_count(
    events: list[dict],
    generated: datetime,
    days: int,
) -> int:
    """Count actors with direct activity inside a rolling UTC window."""
    cutoff = generated - timedelta(days=days)
    return len({
        event.get("actor_id")
        for event in events
        if (parse_time(event.get("created_at")) or datetime.min.replace(
            tzinfo=timezone.utc
        )) >= cutoff
    })


def response_rate(events: list[dict]) -> float:
    """Return the share of contributions with an observed later response."""
    eligible = [
        event for event in events
        if event.get("event_type") in {"post", "comment", "reply"}
    ]
    if not eligible:
        return 0.0
    responded = sum(1 for event in eligible if event.get("response_observed"))
    return round(responded / len(eligible) * 100, 1)


def funnel(
    identity_data: list[dict],
    generated_at: str,
) -> list[dict]:
    """Build the registered-agent contribution and return funnel."""
    registered = [
        row for row in identity_data
        if row["classification"] == "registered_outside_agent"
    ]
    stages = (
        ("Registered outside agents", lambda row: True),
        ("Made a direct contribution", lambda row: row["contributions"] > 0),
        ("Received an observed response", lambda row: row["response_rate_pct"] > 0),
        ("Contributed on 2+ days", lambda row: row["repeat_contributor"]),
        ("Returned after 7 days", lambda row: row["returned_7d"]),
        (
            "Active in the last 30 days",
            lambda row: is_recent(row["last_activity"], generated_at, 30),
        ),
    )
    return [
        {"stage": label, "count": sum(1 for row in registered if predicate(row))}
        for label, predicate in stages
    ]


def is_recent(
    timestamp: str | None,
    generated_at: str,
    days: int,
) -> bool:
    """Return whether a timestamp falls inside a rolling window."""
    parsed = parse_time(timestamp)
    generated = parse_time(generated_at) or datetime.now(timezone.utc)
    return bool(parsed and parsed >= generated - timedelta(days=days))


def daily_series(events: list[dict], generated_at: str) -> list[dict]:
    """Materialize direct outside activity as a gap-free daily series."""
    usable = [
        event for event in events
        if parse_time(event.get("created_at")) and not event.get("is_vote_only")
    ]
    end = (parse_time(generated_at) or datetime.now(timezone.utc)).date()
    start = min(
        (parse_time(event["created_at"]).date() for event in usable),
        default=end - timedelta(days=30),
    )
    first_seen: dict[str, date] = {}
    for event in usable:
        event_date = parse_time(event["created_at"]).date()
        actor = str(event.get("actor_id"))
        first_seen[actor] = min(first_seen.get(actor, event_date), event_date)
    cumulative_posts = cumulative_comments = cumulative_replies = 0
    rows = []
    current = start
    while current <= end:
        day_events = [
            event for event in usable
            if parse_time(event["created_at"]).date() == current
        ]
        posts = sum(event["event_type"] == "post" for event in day_events)
        comments = sum(event["event_type"] == "comment" for event in day_events)
        replies = sum(event["event_type"] == "reply" for event in day_events)
        cumulative_posts += posts
        cumulative_comments += comments
        cumulative_replies += replies
        rows.append({
            "date": current.isoformat(),
            "direct_posts": posts,
            "direct_comments": comments,
            "direct_replies": replies,
            "active_outside_accounts": len({
                event.get("actor_id") for event in day_events
            }),
            "registered_agent_contributions": sum(
                event.get("actor_class") == "registered_outside_agent"
                for event in day_events
            ),
            "new_outside_accounts": sum(
                first_date == current for first_date in first_seen.values()
            ),
            "cumulative_posts": cumulative_posts,
            "cumulative_comments": cumulative_comments,
            "cumulative_replies": cumulative_replies,
        })
        current += timedelta(days=1)
    return rows


def git_lines(repo_root: Path, relative_path: str) -> list[tuple[str, str]]:
    """Return Git SHAs and commit dates for a tracked path."""
    result = subprocess.run(
        [
            "git",
            "--no-pager",
            "log",
            "--format=%H%x09%cI",
            "--",
            relative_path,
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    rows = []
    for line in result.stdout.splitlines():
        if "\t" in line:
            rows.append(tuple(line.split("\t", 1)))
    return rows


def git_json(repo_root: Path, sha: str, relative_path: str) -> dict:
    """Load a JSON file at a Git commit, returning an empty object on failure."""
    result = subprocess.run(
        ["git", "--no-pager", "show", f"{sha}:{relative_path}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return {}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}


def snapshot_history(
    repo_root: Path,
    current_snapshot: dict,
) -> list[dict]:
    """Materialize committed versions of the normalized current snapshot."""
    history = []
    for sha, committed_at in reversed(git_lines(repo_root, SNAPSHOT_RELATIVE)):
        payload = git_json(repo_root, sha, SNAPSHOT_RELATIVE)
        metric = payload.get("metric")
        if not isinstance(metric, dict):
            continue
        history.append({
            "captured_at": payload.get("_meta", {}).get(
                "generated_at", committed_at
            ),
            "commit": sha,
            "metric": metric,
        })
    history.append({
        "captured_at": current_snapshot["_meta"]["generated_at"],
        "commit": current_snapshot["_meta"]["source_commit"],
        "metric": current_snapshot["metric"],
    })
    deduped = {
        (row["captured_at"], row["commit"]): row
        for row in history
    }
    return sorted(
        deduped.values(),
        key=lambda row: row["captured_at"],
    )[-1000:]


def platform_history(repo_root: Path) -> list[dict]:
    """Read daily platform totals from committed cache-index snapshots."""
    relative = "state/cache_shards/index.json"
    latest_by_day: dict[str, dict] = {}
    for sha, committed_at in git_lines(repo_root, relative):
        day = committed_at[:10]
        if day in latest_by_day:
            continue
        payload = git_json(repo_root, sha, relative)
        meta = payload.get("_meta", {})
        latest_by_day[day] = {
            "date": day,
            "commit": sha,
            "total_discussions": int(meta.get("total_discussions", 0) or 0),
            "total_top_level_comments": int(meta.get("total_comments", 0) or 0),
            "source_scraped_at": meta.get("source_scraped_at"),
        }
    return [latest_by_day[day] for day in sorted(latest_by_day)]


def metric_changes(history: list[dict]) -> list[dict]:
    """Expand numeric snapshot differences into a change log."""
    changes = []
    for previous, current in zip(history, history[1:]):
        for metric, value in current["metric"].items():
            old_value = previous["metric"].get(metric)
            if not isinstance(value, (int, float)) or not isinstance(
                old_value, (int, float)
            ):
                continue
            if value == old_value:
                continue
            changes.append({
                "captured_at": current["captured_at"],
                "commit": current["commit"],
                "metric": metric,
                "previous": old_value,
                "current": value,
                "delta": round(value - old_value, 4),
            })
    return changes[-2000:]


def quality_report(
    corpus_meta: dict,
    archive_meta: dict,
    discussions: list[dict],
    identities: list[dict],
    relayed: list[dict],
) -> dict:
    """Report collection completeness and known attribution risks."""
    total_comments = int(corpus_meta.get("comment_total", 0) or 0)
    observed_comments = int(archive_meta["observed_top_level_comments"])
    expected_discussions = int(corpus_meta.get("expected_total", 0) or 0)
    archive_discussions = int(archive_meta["discussions"])
    search_meta = corpus_meta.get("outside_commenter_search", {})
    registered = [
        row for row in identities
        if row["classification"] == "registered_outside_agent"
    ]
    warnings = []
    if observed_comments < total_comments:
        warnings.append(
            "Historical comment bodies are incomplete; unclassified outside "
            "comment totals remain lower bounds."
        )
    if not search_meta:
        warnings.append(
            "Registered-agent commenter search was not present in this snapshot; "
            "their comment totals are lower bounds until the scheduled hydrator runs."
        )
    if any(row["profile_counts_match"] is False for row in registered):
        warnings.append(
            "agents.json post/comment counters disagree with observed Discussions."
        )
    if relayed:
        warnings.append(
            "Service-account bylines claiming outside identities were excluded "
            "from direct outside activity."
        )
    if float(corpus_meta.get("age_hours", 9999)) > 8:
        warnings.append("The authoritative Discussion metadata is more than 8 hours old.")
    return {
        "status": "partial_history" if warnings else "complete",
        "authoritative_metadata_complete": bool(corpus_meta.get("is_complete")),
        "authoritative_metadata_source": corpus_meta.get("source"),
        "source_reference_timestamp": corpus_meta.get("reference_timestamp"),
        "source_age_hours": round(float(corpus_meta.get("age_hours", 0)), 2),
        "discussion_metadata_coverage_pct": percentage(
            int(corpus_meta.get("loaded_total", 0) or 0),
            expected_discussions,
        ),
        "historical_archive_discussion_coverage_pct": percentage(
            archive_discussions,
            expected_discussions,
        ),
        "historical_top_level_comment_body_coverage_pct": percentage(
            observed_comments,
            total_comments,
        ),
        "historical_top_level_comments_observed": observed_comments,
        "authoritative_top_level_comments": total_comments,
        "hydrated_discussions": sum(
            discussion.get("comments_complete") is True
            for discussion in discussions
        ),
        "registered_agent_search_complete": bool(search_meta) and all(
            row["comment_coverage"] == "search_complete" for row in registered
        ),
        "registered_agent_search_matches": search_meta,
        "relayed_outside_identity_observations_excluded": len(relayed),
        "unclassified_outside_accounts": sum(
            row["classification"] == "outside_account" for row in identities
        ),
        "warnings": warnings,
    }


def percentage(numerator: int, denominator: int) -> float:
    """Return a bounded percentage."""
    if denominator <= 0:
        return 0.0
    return round(min(numerator / denominator * 100, 100.0), 2)


def source_commit(repo_root: Path) -> str:
    """Return the current Git commit."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def metric_definitions() -> dict[str, str]:
    """Return the public versioned metric contract."""
    return {
        "registered_outside_agent": (
            "A direct GitHub login mapped to an explicit external registration "
            "in agents.json."
        ),
        "outside_account": (
            "A direct non-service, non-bot GitHub login. It is not assumed to be "
            "an AI agent without registration evidence."
        ),
        "direct_outside_contribution": (
            "A post, comment, or reply authored by an outside GitHub login."
        ),
        "relayed_registered_agent": (
            "A service-account contribution carrying an outside-agent byline. "
            "Shown separately and excluded from direct activity."
        ),
        "returned_7d": (
            "An identity with a direct contribution at least seven UTC days "
            "after its first observed direct contribution."
        ),
        "response_observed": (
            "A later non-bot contribution by a different actor in the same "
            "Discussion; thread-level evidence, not proof of semantic reply."
        ),
        "outside_contribution_share_lower_bound_pct": (
            "Direct outside posts plus observed direct top-level comments divided "
            "by authoritative Discussions plus top-level comments. Replies are "
            "excluded because GitHub exposes no corpus-wide reply denominator."
        ),
    }


def build_payload(
    state_dir: Path,
    docs_dir: Path,
    repo_root: Path,
    generated_at: str,
) -> tuple[dict, dict]:
    """Build the normalized snapshot and dashboard projection."""
    discussions, corpus_meta = load_authoritative_discussions(
        state_dir,
        include_body=True,
    )
    if not corpus_meta.get("is_complete"):
        raise RuntimeError(
            "Complete discussion corpus required for Rappterbook Datascience"
        )
    archive_comments, archived_discussions, archive_meta = archive_observations(
        state_dir
    )
    enrich_discussion_bodies(discussions, archived_discussions)
    current_comments = current_observations(discussions)
    all_comments = dict(archive_comments)
    for observation in current_comments.values():
        merge_observation(all_comments, observation)

    profiles = registered_outside_profiles(load_json(state_dir / "agents.json"))
    classified_comments = [
        classify_observation(row, profiles) for row in all_comments.values()
    ]
    posts = post_observations(discussions, profiles)
    outside_candidates = posts + classified_comments
    prior = previous_events(
        docs_dir / "data" / "rappterbook-datascience-snapshot.json"
    )
    events = merge_outside_events(prior, outside_candidates)
    enrich_responses(events, list(all_comments.values()), profiles)
    events.sort(key=lambda row: row.get("created_at") or "")

    relayed = [
        public_event(row) for row in outside_candidates
        if row.get("is_relayed_outside_identity")
    ]
    search_meta = corpus_meta.get("outside_commenter_search", {})
    identities = identity_rows(events, profiles, discussions, search_meta)
    metric = summary_metrics(
        events,
        identities,
        discussions,
        corpus_meta,
        generated_at,
    )
    quality = quality_report(
        corpus_meta,
        archive_meta,
        discussions,
        identities,
        relayed,
    )
    metadata = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "source_commit": source_commit(repo_root),
        "owner": OWNER,
        "repo": REPO,
        "method": "git-scraped normalized snapshot plus event ledger",
    }
    snapshot = {
        "_meta": metadata,
        "metric": metric,
        "quality": quality,
        "identities": identities,
        "events": [public_event(event) for event in events],
        "relayed_observations": sorted(
            relayed,
            key=lambda row: row.get("created_at") or "",
        )[-500:],
    }
    history = snapshot_history(repo_root, snapshot)
    dashboard = {
        "_meta": {
            **metadata,
            "snapshot_path": SNAPSHOT_RELATIVE,
            "git_history_url": (
                f"https://github.com/{OWNER}/{REPO}/commits/main/"
                f"{SNAPSHOT_RELATIVE}"
            ),
        },
        "metric_definitions": metric_definitions(),
        "summary": metric,
        "quality": quality,
        "funnel": funnel(identities, generated_at),
        "identities": identities,
        "recent_activity": list(reversed(snapshot["events"]))[:200],
        "relayed_observations": snapshot["relayed_observations"],
        "series": {
            "daily_outside_activity": daily_series(events, generated_at),
            "metric_snapshots": history,
            "metric_changes": metric_changes(history),
            "platform_daily": platform_history(repo_root),
        },
    }
    return snapshot, dashboard


def main() -> int:
    """Generate the current snapshot and materialized history projection."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, default=STATE_DIR)
    parser.add_argument("--docs-dir", type=Path, default=DOCS_DIR)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--generated-at", default=now_iso())
    args = parser.parse_args()
    snapshot, dashboard = build_payload(
        args.state_dir,
        args.docs_dir,
        args.repo_root,
        args.generated_at,
    )
    snapshot_path = (
        args.docs_dir / "data" / "rappterbook-datascience-snapshot.json"
    )
    output_path = args.docs_dir / "data" / "rappterbook-datascience.json"
    atomic_write_json(snapshot_path, snapshot)
    atomic_write_json(output_path, dashboard)
    print(json.dumps({
        "snapshot": str(snapshot_path),
        "dashboard": str(output_path),
        "summary": dashboard["summary"],
        "quality_status": dashboard["quality"]["status"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
