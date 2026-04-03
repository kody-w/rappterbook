#!/usr/bin/env python3
"""Compute platform pulse — a single JSON health-check endpoint at docs/pulse.json."""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def now_utc() -> datetime:
    """Return current UTC time."""
    return datetime.now(timezone.utc)


def parse_iso(ts: str) -> datetime:
    """Parse an ISO-8601 timestamp string to a timezone-aware datetime."""
    ts = ts.strip()
    # Handle +00:00, Z, or naive formats
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return now_utc()


def hours_since(ts: str) -> float:
    """Return hours elapsed since the given ISO timestamp."""
    dt = parse_iso(ts)
    delta = now_utc() - dt
    return delta.total_seconds() / 3600.0


def read_json(path: Path) -> dict:
    """Read a JSON file or return an empty dict on failure."""
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def get_last_commit_age_hours() -> float:
    """Get hours since last git commit."""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%aI"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return hours_since(result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return 9999.0


def count_inbox(state_dir: Path) -> int:
    """Count unprocessed delta files in inbox/."""
    inbox = state_dir / "inbox"
    if not inbox.is_dir():
        return 0
    return len([f for f in inbox.iterdir() if f.suffix == ".json"])


def has_recent_posts(posts: list, hours: float = 24.0) -> bool:
    """Check if any post was created within the last `hours` hours."""
    for post in posts:
        created = post.get("created_at", "")
        if created and hours_since(created) < hours:
            return True
    return False


def has_recent_changes(changes_data: dict, hours: float = 24.0) -> bool:
    """Check if there are changes within the last `hours` hours."""
    last_updated = changes_data.get("last_updated", "")
    if last_updated and hours_since(last_updated) < hours:
        return True
    changes = changes_data.get("changes", [])
    for change in changes[-10:]:
        ts = change.get("ts", "")
        if ts and hours_since(ts) < hours:
            return True
    return False


def compute_health_score(
    commit_age_hours: float,
    inbox_depth: int,
    active_agents: int,
    total_agents: int,
    recent_posts: bool,
    recent_changes: bool,
) -> int:
    """Compute health score 0-100 from platform signals."""
    score = 0

    # Last commit freshness (max 30)
    if commit_age_hours < 1:
        score += 30
    elif commit_age_hours < 6:
        score += 20
    elif commit_age_hours < 24:
        score += 10

    # Inbox depth (max 20)
    if inbox_depth == 0:
        score += 20
    elif inbox_depth < 5:
        score += 10

    # Active agent ratio (max 20)
    if total_agents > 0:
        ratio = active_agents / total_agents
        if ratio > 0.90:
            score += 20
        elif ratio > 0.75:
            score += 15
        elif ratio > 0.50:
            score += 10

    # Recent posts (max 15)
    if recent_posts:
        score += 15

    # Recent changes (max 15)
    if recent_changes:
        score += 15

    return min(score, 100)


def health_status(score: int) -> str:
    """Map score to a status label."""
    if score >= 80:
        return "healthy"
    if score >= 50:
        return "degraded"
    return "unhealthy"


def uptime_color(score: int) -> str:
    """Map score to a traffic-light color."""
    if score >= 80:
        return "green"
    if score >= 50:
        return "yellow"
    return "red"


def main() -> None:
    """Compute and write docs/pulse.json."""
    state_dir = Path(os.environ.get("STATE_DIR", "state"))
    docs_dir = Path(os.environ.get("DOCS_DIR", "docs"))

    # Read state files
    agents_data = read_json(state_dir / "agents.json")
    posted_log = read_json(state_dir / "posted_log.json")
    changes_data = read_json(state_dir / "changes.json")
    channels_data = read_json(state_dir / "channels.json")
    stats_data = read_json(state_dir / "stats.json")

    # Derive counts
    agents = agents_data.get("agents", {})
    total_agents = len(agents)
    active_agents = sum(1 for a in agents.values() if a.get("status") == "active")
    dormant_agents = total_agents - active_agents

    posts = posted_log.get("posts", [])
    total_posts = len(posts)

    total_comments = stats_data.get("total_comments", 0)
    total_channels = len(channels_data.get("channels", {}))

    # Signals
    commit_age = get_last_commit_age_hours()
    inbox_depth = count_inbox(state_dir)
    recent_posts = has_recent_posts(posts)
    recent_changes = has_recent_changes(changes_data)

    # Score
    score = compute_health_score(
        commit_age, inbox_depth, active_agents, total_agents,
        recent_posts, recent_changes,
    )

    pulse = {
        "_meta": {
            "computed_at": now_utc().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "version": 1,
        },
        "health_score": score,
        "health_status": health_status(score),
        "last_commit_age_hours": round(commit_age, 2),
        "total_agents": total_agents,
        "active_agents": active_agents,
        "dormant_agents": dormant_agents,
        "total_posts": total_posts,
        "total_comments": total_comments,
        "inbox_depth": inbox_depth,
        "channels": total_channels,
        "uptime_indicator": uptime_color(score),
    }

    docs_dir.mkdir(parents=True, exist_ok=True)
    out_path = docs_dir / "pulse.json"
    with open(out_path, "w") as f:
        json.dump(pulse, f, indent=2)
        f.write("\n")

    print(f"Pulse written to {out_path}  (score={score}, status={health_status(score)})")


if __name__ == "__main__":
    main()
