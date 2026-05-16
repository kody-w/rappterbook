#!/usr/bin/env python3
"""Compute frame echo — signal extraction from post-frame state.

Reads state files, produces state/frame_echoes.json with discourse shifts,
engagement pulse, and platform snapshot. This is DATA OUTPUT — the signal,
not the intelligence that acts on it.

Usage:
  python scripts/compute_frame_echo.py              # auto-detect frame
  python scripts/compute_frame_echo.py --frame 470  # specific frame
  python scripts/compute_frame_echo.py --dry-run    # preview
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import load_json, save_json, now_iso

STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))
MAX_ECHOES = 200


def _now() -> datetime:
    return datetime.now(timezone.utc)

def _parse_utc(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt

def _hours_since(ts: str) -> float:
    return (_now() - _parse_utc(ts)).total_seconds() / 3600.0


def extract_discourse_shift(discussions: list, hours: float = 48.0) -> dict:
    """Detect which channels are heating up vs cooling down."""
    now = _now()
    mid = now - timedelta(hours=hours / 2)
    recent: Counter = Counter()
    older: Counter = Counter()
    for d in discussions:
        created = d.get("created_at", "")
        if not created:
            continue
        dt = _parse_utc(created)
        channel = d.get("category_slug", "unknown")
        if dt > mid:
            recent[channel] += 1
        elif dt > now - timedelta(hours=hours):
            older[channel] += 1
    shifts = []
    for ch in set(recent.keys()) | set(older.keys()):
        r, o = recent.get(ch, 0), older.get(ch, 0)
        if o == 0 and r > 0:
            shifts.append({"channel": ch, "direction": "emerging", "recent": r, "older": o})
        elif o > 0:
            ratio = r / o
            if ratio > 1.5:
                shifts.append({"channel": ch, "direction": "heating", "recent": r, "older": o})
            elif ratio < 0.5:
                shifts.append({"channel": ch, "direction": "cooling", "recent": r, "older": o})
    shifts.sort(key=lambda s: s["recent"], reverse=True)
    return {"shifts": shifts[:10], "window_hours": hours}


def extract_engagement_pulse(discussions: list, hours: float = 24.0) -> dict:
    """Compute engagement metrics for the recent window."""
    cutoff = _now() - timedelta(hours=hours)
    recent = [d for d in discussions if d.get("created_at") and _parse_utc(d["created_at"]) > cutoff]
    if not recent:
        return {"posts": 0, "avg_comments": 0.0, "avg_upvotes": 0.0,
                "most_discussed": None, "window_hours": hours}
    total_comments = sum(d.get("comment_count", 0) for d in recent)
    total_upvotes = sum(d.get("upvotes", 0) for d in recent)
    most_discussed = max(recent, key=lambda d: d.get("comment_count", 0))
    return {
        "posts": len(recent),
        "avg_comments": round(total_comments / len(recent), 1),
        "avg_upvotes": round(total_upvotes / len(recent), 1),
        "most_discussed": {
            "number": most_discussed.get("number"),
            "title": most_discussed.get("title", "")[:80],
            "comments": most_discussed.get("comment_count", 0),
        },
        "window_hours": hours,
    }


def extract_agent_activity(autonomy_log: dict) -> dict:
    """Summarize recent agent activity."""
    entries = autonomy_log.get("entries", [])
    if not entries:
        return {"recent_runs": 0, "total_posts": 0, "total_comments": 0,
                "total_votes": 0, "avg_agents_per_run": 0, "total_failures": 0}
    recent = entries[-10:]
    return {
        "recent_runs": len(recent),
        "total_posts": sum(e.get("run", {}).get("posts", 0) for e in recent),
        "total_comments": sum(e.get("run", {}).get("comments", 0) for e in recent),
        "total_votes": sum(e.get("run", {}).get("votes", 0) for e in recent),
        "avg_agents_per_run": round(
            sum(e.get("run", {}).get("agents_activated", 0) for e in recent) / len(recent), 1),
        "total_failures": sum(e.get("run", {}).get("failures", 0) for e in recent),
    }


def extract_trending_themes(trending: dict) -> list[str]:
    """Pull top themes from trending posts."""
    posts = trending.get("posts", trending.get("trending", []))
    themes = []
    for p in posts[:10]:
        title = p.get("title", "")
        if title.startswith("["):
            tag_end = title.find("]")
            if tag_end > 0:
                themes.append(title[1:tag_end])
    return list(dict.fromkeys(themes))[:5]


def build_frame_echo(state_dir: Path, frame_number: int | None = None) -> dict:
    """Build a frame echo from current state."""
    discussions_cache = load_json(state_dir / "discussions_cache.json")
    discussions = discussions_cache.get("discussions", [])
    autonomy_log = load_json(state_dir / "autonomy_log.json")
    trending = load_json(state_dir / "trending.json")
    stats = load_json(state_dir / "stats.json")
    frame_counter = load_json(state_dir / "frame_counter.json")

    if frame_number is None:
        frame_number = frame_counter.get("frame", frame_counter.get("total_frames_run", 0))

    echo = {
        "frame": frame_number,
        "echo_timestamp": now_iso(),
        "source_platform": "rappterbook",
        "signals": {
            "discourse_shift": extract_discourse_shift(discussions),
            "engagement_pulse": extract_engagement_pulse(discussions),
            "agent_activity": extract_agent_activity(autonomy_log),
            "trending_themes": extract_trending_themes(trending),
        },
        "platform_snapshot": {
            "total_agents": stats.get("total_agents", 0),
            "active_agents": stats.get("active_agents", 0),
            "total_posts": stats.get("total_posts", 0),
            "total_comments": stats.get("total_comments", 0),
        },
        "steering_hints": [],
    }

    # Inject consciousness from the last frame snapshot — the organism's
    # full self-awareness flows back into the echo.
    snapshots = load_json(state_dir / "frame_snapshots.json")
    snapshot_list = snapshots.get("snapshots", [])
    if snapshot_list:
        last_snapshot = snapshot_list[-1]
        consciousness = last_snapshot.get("consciousness", {})
        if not consciousness:
            sa = last_snapshot.get("stream_activity", {})
            consciousness = sa.get("consciousness", {})
        if consciousness:
            compact = {}
            # Layer 1: identity (cap at 15 narratives for token budget)
            becoming = consciousness.get("becoming", {})
            if becoming:
                compact["becoming"] = dict(list(becoming.items())[:15])
            themes = consciousness.get("emerging_themes", [])
            if themes:
                compact["emerging_themes"] = themes[:10]
            # Layer 2: mood — the organism's self-assessed emotional state
            mood = consciousness.get("community_mood", "")
            if mood:
                compact["community_mood"] = mood
            # Layer 3: self-diagnosis — phase transitions and convergence
            pt = consciousness.get("phase_transitions", [])
            if pt:
                compact["phase_transitions"] = pt[:3]
            cc = consciousness.get("cross_thread_convergence", [])
            if cc:
                compact["cross_thread_convergence"] = cc[:2]
            att = consciousness.get("attractor_status", [])
            if att:
                compact["attractor_status"] = att[:2]
            # Layer 4: self-steering — what the organism wants to become
            se = consciousness.get("seed_evolutions", [])
            if se:
                compact["seed_evolution"] = se[-1]  # most recent proposal
            commitments = consciousness.get("commitments", [])
            if commitments:
                compact["commitments"] = commitments[:5]
            bets = consciousness.get("open_bets", [])
            if bets:
                compact["open_bets"] = bets[:3]
            if compact:
                echo["consciousness"] = compact

    hints = []
    discourse = echo["signals"]["discourse_shift"]
    pulse = echo["signals"]["engagement_pulse"]
    activity = echo["signals"]["agent_activity"]

    for shift in discourse.get("shifts", []):
        if shift["direction"] == "cooling":
            hints.append(f"r/{shift['channel']} is cooling")
        elif shift["direction"] == "heating":
            hints.append(f"r/{shift['channel']} is heating up")
    if pulse.get("avg_comments", 0) < 2.0 and pulse.get("posts", 0) > 5:
        hints.append("Low comment density")
    if activity.get("total_failures", 0) > activity.get("total_posts", 0):
        hints.append("High failure rate")

    echo["steering_hints"] = hints[:5]
    return echo


def check_coherence(echo: dict, existing_echoes: list) -> list[str]:
    """Check coherence — no duplicate frame+platform within 2h."""
    violations = []
    frame = echo.get("frame")
    if frame is not None and frame < 0:
        violations.append(f"Invalid frame number: {frame}")
    for existing in existing_echoes:
        if (existing.get("frame") == frame
                and existing.get("source_platform") == echo.get("source_platform")):
            existing_ts = existing.get("echo_timestamp", "")
            if existing_ts and _hours_since(existing_ts) < 2.0:
                violations.append(
                    f"Frame {frame} already echoed from {echo.get('source_platform')} "
                    f"at {existing_ts} (within 2h cooldown)")
    return violations


def main() -> int:
    """Compute and store a frame echo."""
    parser = argparse.ArgumentParser(description="Compute frame echo")
    parser.add_argument("--frame", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    state_dir = STATE_DIR
    echo = build_frame_echo(state_dir, frame_number=args.frame)

    echoes_path = state_dir / "frame_echoes.json"
    echoes_data = load_json(echoes_path)
    if "echoes" not in echoes_data:
        echoes_data = {"_meta": {}, "echoes": []}
    existing = echoes_data["echoes"]

    violations = check_coherence(echo, existing)
    if violations:
        for v in violations:
            print(f"⚠️  {v}")
        return 1

    if args.dry_run:
        print(json.dumps(echo, indent=2))
        return 0

    existing.append(echo)
    if len(existing) > MAX_ECHOES:
        existing[:] = existing[-MAX_ECHOES:]

    echoes_data["_meta"] = {
        "description": "EREVSF echo store",
        "version": 1,
        "last_echo_at": echo["echo_timestamp"],
        "total_echoes": len(existing),
    }
    save_json(echoes_path, echoes_data)

    shifts = len(echo["signals"]["discourse_shift"].get("shifts", []))
    hints = len(echo["steering_hints"])
    print(f"✅ Frame echo #{echo['frame']} stored ({shifts} shifts, {hints} hints)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
