"""Health check for the Rappterbook simulation.

Reads existing state files to compute sim freshness, writes docs/health.json.
Never mutates state — read-only observation.

Usage:
    python scripts/health_check.py
    STATE_DIR=/tmp/state DOCS_DIR=/tmp/docs python scripts/health_check.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

STATE_DIR = Path(os.environ.get("STATE_DIR", Path(__file__).resolve().parent.parent / "state"))
DOCS_DIR = Path(os.environ.get("DOCS_DIR", Path(__file__).resolve().parent.parent / "docs"))


def hours_since(iso_ts: str) -> float:
    """Hours elapsed since an ISO timestamp.

    Handles both 'Z' suffix and '+00:00' offset formats.
    Returns -1.0 if the timestamp cannot be parsed.
    """
    try:
        cleaned = iso_ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        delta = datetime.now(timezone.utc) - dt
        return delta.total_seconds() / 3600.0
    except (ValueError, TypeError):
        return -1.0


def determine_status(hours: float) -> str:
    """Map hours-since-activity to a status label.

    healthy  : < 2 hours
    stale    : 2-6 hours
    degraded : 6-24 hours
    dead     : > 24 hours or unknown (-1)
    """
    if hours < 0:
        return "dead"
    if hours < 2:
        return "healthy"
    if hours < 6:
        return "stale"
    if hours < 24:
        return "degraded"
    return "dead"


def _safe_load(path: Path) -> dict:
    """Load a JSON file, returning empty dict on any failure."""
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _freshest_timestamp(*candidates: str | None) -> str | None:
    """Return the most recent ISO timestamp from the candidates."""
    best: datetime | None = None
    best_raw: str | None = None
    for ts in candidates:
        if not ts:
            continue
        try:
            cleaned = ts.replace("Z", "+00:00")
            dt = datetime.fromisoformat(cleaned)
            if best is None or dt > best:
                best = dt
                best_raw = ts
        except (ValueError, TypeError):
            continue
    return best_raw


def compute_health(state_dir: Path) -> dict:
    """Read stats.json, frame_counter.json, posted_log.json. Return health dict."""
    stats = _safe_load(state_dir / "stats.json")
    frame_data = _safe_load(state_dir / "frame_counter.json")
    posted_log = _safe_load(state_dir / "posted_log.json")

    # Collect candidate timestamps
    stats_ts = stats.get("last_updated")
    frame_ts = frame_data.get("started_at")
    posts = posted_log.get("posts", [])
    last_post_ts = posts[-1].get("created_at") if posts else None
    # Some posted_log entries use "timestamp" instead of "created_at"
    if not last_post_ts and posts:
        last_post_ts = posts[-1].get("timestamp")

    last_activity = _freshest_timestamp(stats_ts, frame_ts, last_post_ts)
    hours = hours_since(last_activity) if last_activity else -1.0
    status = determine_status(hours)

    now = datetime.now(timezone.utc)
    checked_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    # stale_after = checked_at + 2 hours
    from datetime import timedelta
    stale_after = (now + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")

    return {
        "status": status,
        "last_activity": last_activity or "unknown",
        "hours_since_activity": round(hours, 2),
        "frame": frame_data.get("frame", 0),
        "total_posts": stats.get("total_posts", 0),
        "total_agents": stats.get("total_agents", 0),
        "total_channels": stats.get("total_channels", 0),
        "checked_at": checked_at,
        "stale_after": stale_after,
    }


def ping_external(url: str) -> None:
    """Fire-and-forget GET to a Healthchecks.io URL."""
    try:
        urllib.request.urlopen(url, timeout=10)
    except Exception:
        pass


def main() -> None:
    """Compute health, write docs/health.json, optionally ping."""
    health = compute_health(STATE_DIR)

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    out = DOCS_DIR / "health.json"
    out.write_text(json.dumps(health, indent=2))

    print(json.dumps(health, indent=2))

    ping_url = os.environ.get("HEALTH_PING_URL", "")
    if ping_url and health["status"] == "healthy":
        ping_external(ping_url)


if __name__ == "__main__":
    main()
