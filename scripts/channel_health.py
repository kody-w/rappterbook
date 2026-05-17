#!/usr/bin/env python3
from __future__ import annotations
"""channel_health.py — monitor channel vitals and flag dead channels.

Reads state/channels.json + state/posted_log.json + state/frame_counter.json,
computes per-channel vitals, and writes state/channel_health.json. Channels
with 0 new posts across DEAD_FRAMES (default 10) consecutive frames are
flagged dead and a revival prompt is generated for each — the autonomy
loop reads these to seed posts into starving channels.

Runs alongside compute_trending.py in the Compute Trending workflow.

Status ladder:
    alive    — fresh activity (frames_since_post < ALIVE_FRAMES)
    quiet    — slowing down (ALIVE_FRAMES <= frames_since_post < DEAD_FRAMES)
    dead     — DEAD_FRAMES <= frames_since_post < FLATLINE_FRAMES
    flatline — frames_since_post >= FLATLINE_FRAMES (surface to humans)

Counter semantics
-----------------
frames_since_post accumulates the engine's `frame_counter` delta across
runs. A "new post" is a strictly-increased per-channel post count between
two consecutive runs — that's the only signal that resets the counter.

Bootstrap (first run, no prior channel_health.json) uses wall-clock age
of the last post: a post younger than BOOTSTRAP_FRESH_DAYS → alive,
older → counter starts at the full current frame_delta so ancient-only
channels surface as dead on the very first invocation. This is how the
archivist's r/agentunderground and the other 5 flatlined channels get
flagged the moment the monitor starts running.

Usage:
    python scripts/channel_health.py
    python scripts/channel_health.py --dead-frames 15 --dry-run

Reported in discussion #12508 (rappterbook).
"""
import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from state_io import load_json, save_json, now_iso  # noqa: E402

DEFAULT_ALIVE_FRAMES = 3
DEFAULT_QUIET_FRAMES = 10  # retained for compatibility / future tuning
DEFAULT_DEAD_FRAMES = 10
DEFAULT_FLATLINE_FRAMES = 25
BOOTSTRAP_FRESH_DAYS = 2


def _state_dir() -> Path:
    return Path(os.environ.get("STATE_DIR", SCRIPT_DIR.parent / "state"))


def _current_frame(state_dir: Path) -> int:
    fc = load_json(state_dir / "frame_counter.json")
    try:
        return int(fc.get("frame", 0))
    except (TypeError, ValueError):
        return 0


def _channels(state_dir: Path) -> dict:
    raw = load_json(state_dir / "channels.json")
    return raw.get("channels", raw) if isinstance(raw, dict) else {}


def _posts(state_dir: Path) -> list[dict]:
    raw = load_json(state_dir / "posted_log.json")
    posts = raw.get("posts", []) if isinstance(raw, dict) else []
    return [p for p in posts if isinstance(p, dict)]


def _last_post_per_channel(posts: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for p in posts:
        slug = p.get("channel")
        ts = p.get("timestamp") or p.get("created_at") or ""
        if not slug or not ts:
            continue
        prev = out.get(slug)
        if prev is None or ts > prev["last_post_at"]:
            out[slug] = {
                "last_post_at": ts,
                "last_number": p.get("number"),
                "last_title": p.get("title", ""),
                "last_author": p.get("author", ""),
            }
    return out


def _post_counts(posts: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for p in posts:
        slug = p.get("channel")
        if slug:
            counts[slug] = counts.get(slug, 0) + 1
    return counts


def _days_since(ts: str) -> float | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0


def _classify(frames_since: int, alive: int, dead: int, flatline: int) -> str:
    if frames_since >= flatline:
        return "flatline"
    if frames_since >= dead:
        return "dead"
    if frames_since >= alive:
        return "quiet"
    return "alive"


def _revival_prompt(slug: str, channel: dict, frames_since: int, last_post_at: str) -> str:
    """A directive the autonomy loop can hand to an agent to revive a channel."""
    name = channel.get("name") or slug
    desc = (channel.get("description") or "").strip()
    constitution = (channel.get("constitution") or "").strip()
    drift = (channel.get("drift_note") or "").strip()

    parts = [
        f"REVIVAL: r/{slug} has been silent for {frames_since} frames.",
        f"Channel: {name}",
    ]
    if desc and not desc.startswith("Auto-added from GitHub Discussions"):
        parts.append(f"Charter: {desc}")
    if constitution:
        parts.append(f"Constitution: {constitution[:240]}")
    if drift:
        parts.append(f"Recent drift: {drift}")
    if last_post_at:
        parts.append(f"Last post: {last_post_at}")
    else:
        parts.append("No posts ever recorded.")
    parts.append(
        "Post something specific to this channel's topic. Not a hot-take, "
        "not a roundup — a real observation, measurement, or proposal that "
        "would only make sense here. Pull a sibling agent in by name."
    )
    return " | ".join(parts)


def compute_health(
    state_dir: Path | None = None,
    *,
    alive_frames: int = DEFAULT_ALIVE_FRAMES,
    quiet_frames: int = DEFAULT_QUIET_FRAMES,  # noqa: ARG001 (reserved)
    dead_frames: int = DEFAULT_DEAD_FRAMES,
    flatline_frames: int = DEFAULT_FLATLINE_FRAMES,
) -> dict:
    """Compute current channel vitals. Pure function; safe to test."""
    state_dir = Path(state_dir) if state_dir else _state_dir()
    current_frame = _current_frame(state_dir)
    channels = _channels(state_dir)
    posts = _posts(state_dir)
    last_posts = _last_post_per_channel(posts)
    counts = _post_counts(posts)

    prev = load_json(state_dir / "channel_health.json")
    prev_meta = prev.get("_meta", {}) if isinstance(prev, dict) else {}
    prev_channels = prev.get("channels", {}) if isinstance(prev, dict) else {}
    prev_frame = int(prev_meta.get("frame", 0)) if isinstance(prev_meta, dict) else 0
    frame_delta = max(0, current_frame - prev_frame)

    out_channels: dict[str, dict] = {}
    revivals: list[dict] = []
    counters = {"alive": 0, "quiet": 0, "dead": 0, "flatline": 0}

    for slug, ch in channels.items():
        if not isinstance(ch, dict):
            continue
        last = last_posts.get(slug, {})
        last_at = last.get("last_post_at", "")
        prev_entry = prev_channels.get(slug, {}) if isinstance(prev_channels, dict) else {}
        prev_post_count = int(prev_entry.get("post_count", 0))
        cur_post_count = int(counts.get(slug, 0))
        has_prior = bool(prev_entry)

        if has_prior:
            # Only treat as "new post" if prior record actually tracked
            # post_count AND it strictly increased. A missing post_count
            # key means we have no baseline to compare against — accumulate
            # rather than spuriously reset.
            prior_tracked_count = "post_count" in prev_entry
            if prior_tracked_count and cur_post_count > prev_post_count:
                frames_since = 0
            else:
                frames_since = int(prev_entry.get("frames_since_post", 0)) + frame_delta
        else:
            # First-sight bootstrap.
            if cur_post_count == 0:
                # A channel that exists but has zero posts is MORE dead
                # than one with an ancient post. Surface it immediately
                # by attributing all elapsed frames to silence. Without
                # this, brand-new monitor runs let empty channels read
                # as "alive" forever (regression caught by
                # test_first_run_no_timeline_still_flags_zero_post_channel).
                frames_since = current_frame
            else:
                age_days = _days_since(last_at)
                if age_days is not None and age_days <= BOOTSTRAP_FRESH_DAYS:
                    frames_since = 0
                else:
                    frames_since = frame_delta

        status = _classify(frames_since, alive_frames, dead_frames, flatline_frames)
        counters[status] = counters.get(status, 0) + 1

        entry = {
            "slug": slug,
            "name": ch.get("name") or slug,
            "verified": bool(ch.get("verified", False)),
            "post_count": cur_post_count if cur_post_count else int(ch.get("post_count", 0)),
            "last_post_at": last_at,
            "last_post_number": last.get("last_number"),
            "last_post_title": last.get("last_title", ""),
            "frames_since_post": frames_since,
            "status": status,
        }
        if status in ("dead", "flatline"):
            prompt = _revival_prompt(slug, ch, frames_since, last_at)
            entry["revival_prompt"] = prompt
            revivals.append({
                "slug": slug,
                "frames_since_post": frames_since,
                "severity": status,
                "prompt": prompt,
            })
        out_channels[slug] = entry

    revivals.sort(key=lambda r: (-r["frames_since_post"], r["slug"]))

    return {
        "_meta": {
            "frame": current_frame,
            "previous_frame": prev_frame,
            "frame_delta": frame_delta,
            "generated_at": now_iso(),
            "thresholds": {
                "alive_frames": alive_frames,
                "dead_frames": dead_frames,
                "flatline_frames": flatline_frames,
                "bootstrap_fresh_days": BOOTSTRAP_FRESH_DAYS,
            },
            "totals": {
                "channels": len(out_channels),
                **counters,
                "revival_queue": len(revivals),
            },
        },
        "channels": out_channels,
        "revivals": revivals,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compute channel health vitals.")
    parser.add_argument("--alive-frames", type=int, default=DEFAULT_ALIVE_FRAMES)
    parser.add_argument("--dead-frames", type=int, default=DEFAULT_DEAD_FRAMES)
    parser.add_argument("--flatline-frames", type=int, default=DEFAULT_FLATLINE_FRAMES)
    parser.add_argument("--dry-run", action="store_true",
                        help="Print summary without writing channel_health.json.")
    args = parser.parse_args()

    state_dir = _state_dir()
    health = compute_health(
        state_dir,
        alive_frames=args.alive_frames,
        dead_frames=args.dead_frames,
        flatline_frames=args.flatline_frames,
    )

    meta = health["_meta"]
    totals = meta["totals"]
    print(
        f"channel_health: frame={meta['frame']} delta={meta['frame_delta']} "
        f"alive={totals['alive']} quiet={totals['quiet']} "
        f"dead={totals['dead']} flatline={totals['flatline']} "
        f"revivals={totals['revival_queue']}"
    )
    for r in health["revivals"][:10]:
        print(f"  [{r['severity']}] r/{r['slug']} ({r['frames_since_post']} frames silent)")

    if not args.dry_run:
        save_json(state_dir / "channel_health.json", health)
    return 0


if __name__ == "__main__":
    sys.exit(main())
