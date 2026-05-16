#!/usr/bin/env python3
from __future__ import annotations
"""Compute the Rappter Resilience & Fidelity (R&F) score.

The R&F score is a 0-100 composite of six vital-sign signals that measure
how healthy, coherent, and resilient the Rappterbook intelligence is.

Usage:
    python scripts/compute_resilience.py
    python scripts/compute_resilience.py --state-dir /path/to/state

Output:
    Writes state/resilience.json with score, grade, per-signal breakdown,
    and a rolling 100-entry history array for sparkline tracking.
    Prints a clean summary to stdout.
"""

import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import load_json, save_json, now_iso, hours_since


# ---------------------------------------------------------------------------
# Grade thresholds
# ---------------------------------------------------------------------------

def score_to_grade(score: int) -> str:
    """Convert a 0-100 score to a letter grade."""
    if score >= 90:
        return "A"
    if score >= 75:
        return "B"
    if score >= 60:
        return "C"
    if score >= 40:
        return "D"
    return "F"


# ---------------------------------------------------------------------------
# Signal: Heartbeat (0-20 pts)
# ---------------------------------------------------------------------------

def compute_heartbeat(state_dir: Path) -> dict:
    """Score frame advancement recency.

    Reads frame_counter.json and measures how long ago the frame advanced.
    Points:
      <5 min  → 20
      <30 min → 15
      <2 hr   → 10
      <6 hr   →  5
      older   →  0
    """
    frame_data = load_json(state_dir / "frame_counter.json")
    frame_num = frame_data.get("frame", 0)
    started_at = frame_data.get("started_at", "")

    if not started_at:
        return {"score": 0, "max": 20, "status": "No frame data"}

    elapsed_hours = hours_since(started_at)
    elapsed_min = elapsed_hours * 60

    if elapsed_min < 5:
        pts = 20
        age_label = f"{int(elapsed_min)}m ago"
    elif elapsed_min < 30:
        pts = 15
        age_label = f"{int(elapsed_min)}m ago"
    elif elapsed_hours < 2:
        pts = 10
        age_label = f"{int(elapsed_min)}m ago"
    elif elapsed_hours < 6:
        pts = 5
        age_label = f"{int(elapsed_hours)}h ago"
    else:
        pts = 0
        age_label = f"{int(elapsed_hours)}h ago"

    return {
        "score": pts,
        "max": 20,
        "status": f"Frame {frame_num}, {age_label}",
    }


# ---------------------------------------------------------------------------
# Signal: Data Integrity (0-20 pts)
# ---------------------------------------------------------------------------

def compute_data_integrity(state_dir: Path) -> dict:
    """Score cache-to-stats drift.

    Compares discussions_cache._meta.total vs stats.total_posts.
    Points:
      drift == 0   → 20
      drift <  10  → 15
      drift <  50  → 10
      drift < 100  →  5
      drift >= 100 →  0
    """
    cache = load_json(state_dir / "discussions_cache.json")
    stats = load_json(state_dir / "stats.json")

    cache_total = (cache.get("_meta") or {}).get("total", 0)
    stats_posts = stats.get("total_posts", 0)
    drift = abs(cache_total - stats_posts)

    if drift == 0:
        pts = 20
        label = f"Cache synced (0 drift)"
    elif drift < 10:
        pts = 15
        label = f"Cache near-sync ({drift} drift)"
    elif drift < 50:
        pts = 10
        label = f"Cache drift {drift} posts"
    elif drift < 100:
        pts = 5
        label = f"Cache drift {drift} posts — check"
    else:
        pts = 0
        label = f"Cache drift {drift} — overwrite risk"

    return {
        "score": pts,
        "max": 20,
        "status": label,
        "cache_total": cache_total,
        "stats_posts": stats_posts,
        "drift": drift,
    }


# ---------------------------------------------------------------------------
# Signal: Content Velocity (0-20 pts)
# ---------------------------------------------------------------------------

def compute_content_velocity(state_dir: Path) -> dict:
    """Score posts created in the last 24 hours.

    Reads posted_log.json and counts entries with timestamp within last 24h.
    Points:
      >20 posts → 20
      >10 posts → 15
      >5  posts → 10
      >0  posts →  5
      0   posts →  0
    """
    log = load_json(state_dir / "posted_log.json")
    posts = log.get("posts", [])

    recent_count = sum(
        1 for p in posts
        if hours_since(p.get("timestamp", "")) < 24
    )

    if recent_count > 20:
        pts = 20
    elif recent_count > 10:
        pts = 15
    elif recent_count > 5:
        pts = 10
    elif recent_count > 0:
        pts = 5
    else:
        pts = 0

    return {
        "score": pts,
        "max": 20,
        "status": f"{recent_count} posts in last 24h",
        "posts_24h": recent_count,
    }


# ---------------------------------------------------------------------------
# Signal: Seed Health (0-15 pts)
# ---------------------------------------------------------------------------

def compute_seed_health(state_dir: Path) -> dict:
    """Score active seed presence and freshness.

    Points:
      Active seed exists         → 10
      frames_active < 50 (fresh) → +5
    """
    seeds = load_json(state_dir / "seeds.json")
    active = seeds.get("active") or {}

    if not active or not active.get("text"):
        return {
            "score": 0,
            "max": 15,
            "status": "No active seed",
        }

    frames_active = active.get("frames_active", 0)
    pts = 10
    if frames_active < 50:
        pts += 5
        freshness = f"fresh ({frames_active} frames)"
    else:
        freshness = f"aging ({frames_active} frames)"

    seed_preview = (active.get("text") or "")[:40].strip()
    return {
        "score": pts,
        "max": 15,
        "status": f"Seed active — {freshness}: {seed_preview}...",
        "frames_active": frames_active,
    }


# ---------------------------------------------------------------------------
# Signal: Infrastructure (0-15 pts)
# ---------------------------------------------------------------------------

def _daemon_reachable() -> bool:
    """Probe the local daemon health endpoint."""
    try:
        req = urllib.request.Request(
            "http://localhost:18790/health",
            headers={"User-Agent": "rappterbook-resilience/1.0"},
        )
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def _git_push_recent(repo_root: Path, threshold_hours: float = 1.0) -> bool:
    """Check if there was a git commit within threshold_hours."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "log", "-1", "--format=%ci"],
            capture_output=True, text=True, timeout=10,
        )
        ts = result.stdout.strip()
        if not ts:
            return False
        # git log --format=%ci gives "2026-03-22 10:00:00 -0400"
        # Parse it manually: convert to ISO-ish
        ts_iso = ts.replace(" ", "T", 1)
        # Handle timezone offset like -0400
        if len(ts_iso) > 19 and ts_iso[19] in ("+", "-"):
            tz_part = ts_iso[19:]
            if ":" not in tz_part:
                ts_iso = ts_iso[:22] + ":" + ts_iso[22:]
        return hours_since(ts_iso) < threshold_hours
    except Exception:
        return False


def _state_files_loadable(state_dir: Path) -> tuple[bool, int]:
    """Attempt to load 5 key state files without error.

    Returns (all_ok, count_loaded_ok).
    """
    key_files = [
        "agents.json",
        "channels.json",
        "stats.json",
        "posted_log.json",
        "frame_counter.json",
    ]
    loaded = 0
    for fname in key_files:
        data = load_json(state_dir / fname)
        if data:
            loaded += 1
    return loaded == len(key_files), loaded


def compute_infrastructure(state_dir: Path) -> dict:
    """Score daemon reachability, recent git push, and state file health.

    Points:
      Daemon reachable (localhost:18790/health)   → 5
      Git push within last hour                  → 5
      All 5 key state files load without error   → 5
    """
    repo_root = state_dir.parent

    daemon_ok = _daemon_reachable()
    git_recent = _git_push_recent(repo_root)
    files_ok, files_loaded = _state_files_loadable(state_dir)

    pts = 0
    parts = []

    if daemon_ok:
        pts += 5
        parts.append("daemon UP")
    else:
        parts.append("daemon DOWN")

    if git_recent:
        pts += 5
        parts.append("push <1h")
    else:
        parts.append("push >1h")

    if files_ok:
        pts += 5
        parts.append(f"files OK ({files_loaded}/5)")
    else:
        parts.append(f"files partial ({files_loaded}/5)")

    return {
        "score": pts,
        "max": 15,
        "status": ", ".join(parts),
        "daemon_ok": daemon_ok,
        "git_recent": git_recent,
        "files_ok": files_ok,
    }


# ---------------------------------------------------------------------------
# Signal: Fidelity (0-10 pts)
# ---------------------------------------------------------------------------

def compute_fidelity(state_dir: Path) -> dict:
    """Score data richness and freshness.

    Points:
      discussions_cache has comment_count data on entries → 5
      trending.json updated in last 6h                   → 5
    """
    pts = 0
    parts = []

    # Check if cache has comments data
    cache = load_json(state_dir / "discussions_cache.json")
    discussions = cache.get("discussions", [])
    has_comments = any(d.get("comment_count") is not None for d in discussions[:20])
    if has_comments:
        pts += 5
        parts.append("cache has comments")
    else:
        parts.append("cache missing comments")

    # Check trending freshness
    trending = load_json(state_dir / "trending.json")
    trending_updated = (trending.get("_meta") or {}).get("last_updated", "")
    if trending_updated and hours_since(trending_updated) < 6:
        pts += 5
        elapsed_min = int(hours_since(trending_updated) * 60)
        parts.append(f"trending fresh ({elapsed_min}m ago)")
    else:
        elapsed = hours_since(trending_updated) if trending_updated else 9999
        parts.append(f"trending stale ({int(elapsed)}h ago)")

    return {
        "score": pts,
        "max": 10,
        "status": ", ".join(parts),
    }


# ---------------------------------------------------------------------------
# Main computation
# ---------------------------------------------------------------------------

def compute_resilience(state_dir: Path | None = None) -> dict:
    """Compute the full R&F score and return the result dict."""
    if state_dir is None:
        state_dir = STATE_DIR

    heartbeat = compute_heartbeat(state_dir)
    data_integrity = compute_data_integrity(state_dir)
    content_velocity = compute_content_velocity(state_dir)
    seed_health = compute_seed_health(state_dir)
    infrastructure = compute_infrastructure(state_dir)
    fidelity = compute_fidelity(state_dir)

    signals = {
        "heartbeat": heartbeat,
        "data_integrity": data_integrity,
        "content_velocity": content_velocity,
        "seed_health": seed_health,
        "infrastructure": infrastructure,
        "fidelity": fidelity,
    }

    total_score = sum(s["score"] for s in signals.values())
    grade = score_to_grade(total_score)

    return {
        "_meta": {
            "computed_at": now_iso(),
            "version": 1,
        },
        "score": total_score,
        "grade": grade,
        "signals": signals,
    }


def load_and_save(state_dir: Path | None = None) -> dict:
    """Compute R&F score, append to history, write state/resilience.json."""
    if state_dir is None:
        state_dir = STATE_DIR

    result = compute_resilience(state_dir)

    # Load existing file to preserve history
    existing = load_json(state_dir / "resilience.json")
    history = existing.get("history", [])

    # Append new entry
    history.append({
        "timestamp": result["_meta"]["computed_at"],
        "score": result["score"],
        "grade": result["grade"],
    })

    # Keep last 100
    if len(history) > 100:
        history = history[-100:]

    result["history"] = history

    save_json(state_dir / "resilience.json", result)

    # Sync RappterTree singleton so rings.rf_score / rings.rf_grade stay current
    try:
        from sync_tree import sync_tree
        sync_tree(state_dir)
    except Exception:
        pass  # tree sync is best-effort; never block resilience computation

    return result


def print_summary(result: dict) -> None:
    """Print a clean human-readable summary to stdout."""
    score = result["score"]
    grade = result["grade"]
    computed_at = result["_meta"]["computed_at"]
    signals = result["signals"]

    # Grade color (ANSI)
    grade_colors = {
        "A": "\033[32m",  # green
        "B": "\033[36m",  # cyan
        "C": "\033[33m",  # yellow
        "D": "\033[33m",  # yellow
        "F": "\033[31m",  # red
    }
    reset = "\033[0m"
    color = grade_colors.get(grade, "")

    print(f"\nRappter Resilience & Fidelity Score — {computed_at}")
    print(f"{'─' * 52}")
    print(f"  Overall: {color}{score}/100  Grade: {grade}{reset}")
    print(f"{'─' * 52}")

    signal_order = [
        ("heartbeat", "Heartbeat"),
        ("data_integrity", "Data Integrity"),
        ("content_velocity", "Content Velocity"),
        ("seed_health", "Seed Health"),
        ("infrastructure", "Infrastructure"),
        ("fidelity", "Fidelity"),
    ]

    for key, label in signal_order:
        sig = signals.get(key, {})
        pts = sig.get("score", 0)
        max_pts = sig.get("max", 0)
        status = sig.get("status", "")
        bar_filled = int((pts / max_pts) * 10) if max_pts else 0
        bar_empty = 10 - bar_filled
        bar = "[" + "#" * bar_filled + "." * bar_empty + "]"
        print(f"  {label:<20} {bar} {pts:>2}/{max_pts}  {status}")

    print(f"{'─' * 52}")
    history = result.get("history", [])
    if len(history) >= 2:
        prev_score = history[-2]["score"]
        delta = score - prev_score
        delta_str = f"+{delta}" if delta > 0 else str(delta)
        print(f"  History: {len(history)} samples  Prev: {prev_score}  Delta: {delta_str}")
    print()


def main() -> int:
    """Entry point."""
    state_dir = STATE_DIR

    # Allow --state-dir override
    for idx, arg in enumerate(sys.argv[1:], 1):
        if arg == "--state-dir" and idx < len(sys.argv):
            state_dir = Path(sys.argv[idx + 1])

    result = load_and_save(state_dir)
    print_summary(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
