#!/usr/bin/env python3
"""Build frame timeline from git history + state files.

Reconstructs frame-by-frame activity from tick 1 to current:
  - Git commits (all 400 frames — source of truth)
  - Frame snapshots (frames 353-400)
  - Stream deltas (frames 395-400)
  - Posted log correlation (all frames via timestamp)

Outputs: state/frame_timeline.json
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
ROOT = SCRIPTS_DIR.parent
STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))


def run_git(args: list[str]) -> str:
    """Run a git command and return stdout."""
    result = subprocess.run(
        ["git", "--no-pager"] + args,
        capture_output=True, text=True, cwd=str(ROOT),
    )
    return result.stdout


def extract_frames_from_git() -> dict[int, dict]:
    """Extract frame data from git commit messages."""
    frames: dict[int, dict] = {}

    # Get all commits mentioning frame numbers
    log = run_git([
        "log", "--all", "--oneline", "--format=%H|%aI|%s",
        "--grep=frame", "--grep=Frame", "-i",
    ])

    frame_pattern = re.compile(r"[Ff]rame\s+(\d+)")

    for line in log.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("|", 2)
        if len(parts) < 3:
            continue
        commit_hash, timestamp, message = parts

        match = frame_pattern.search(message)
        if not match:
            continue

        frame_num = int(match.group(1))
        if frame_num < 1 or frame_num > 9999:
            continue

        if frame_num not in frames:
            frames[frame_num] = {
                "frame": frame_num,
                "timestamp": timestamp,
                "commits": [],
                "streams": [],
                "posts_count": 0,
                "comments_count": 0,
                "reactions_count": 0,
                "agents_activated": 0,
                "mood": None,
                "trending": [],
                "snapshot": None,
            }

        frames[frame_num]["commits"].append({
            "hash": commit_hash[:10],
            "message": message[:120],
        })

        # Extract stream info from commit message
        stream_match = re.search(r"(solo|alpha|beta|gamma|delta|all streams)", message.lower())
        if stream_match:
            stream = stream_match.group(1)
            if stream not in frames[frame_num]["streams"]:
                frames[frame_num]["streams"].append(stream)

        # Extract activity counts from commit messages
        posts_match = re.search(r"(\d+)\s+posts?", message)
        comments_match = re.search(r"(\d+)\s+comments?", message)
        reactions_match = re.search(r"(\d+)\s+reactions?", message)
        agents_match = re.search(r"(\d+)\s+agents?", message)
        mutations_match = re.search(r"(\d+)\s+mutations?", message)

        if posts_match:
            frames[frame_num]["posts_count"] = max(
                frames[frame_num]["posts_count"], int(posts_match.group(1))
            )
        if comments_match:
            frames[frame_num]["comments_count"] = max(
                frames[frame_num]["comments_count"], int(comments_match.group(1))
            )
        if reactions_match:
            frames[frame_num]["reactions_count"] = max(
                frames[frame_num]["reactions_count"], int(reactions_match.group(1))
            )
        if agents_match:
            frames[frame_num]["agents_activated"] = max(
                frames[frame_num]["agents_activated"], int(agents_match.group(1))
            )
        if mutations_match and not posts_match:
            frames[frame_num]["posts_count"] = max(
                frames[frame_num]["posts_count"], int(mutations_match.group(1))
            )

    return frames


def enrich_with_snapshots(frames: dict[int, dict]) -> None:
    """Add frame snapshot data (frames 353-400)."""
    snap_path = STATE_DIR / "frame_snapshots.json"
    if not snap_path.exists():
        return

    data = json.loads(snap_path.read_text())
    snapshots = data.get("snapshots", [])

    # Group snapshots by frame, keep latest per frame
    by_frame: dict[int, dict] = {}
    for s in snapshots:
        fn = s.get("frame")
        if fn and isinstance(fn, int):
            by_frame[fn] = s

    for frame_num, snap in by_frame.items():
        if frame_num not in frames:
            frames[frame_num] = {
                "frame": frame_num,
                "timestamp": snap.get("timestamp", ""),
                "commits": [],
                "streams": [],
                "posts_count": 0,
                "comments_count": 0,
                "reactions_count": 0,
                "agents_activated": 0,
                "mood": None,
                "trending": [],
                "snapshot": None,
            }

        frames[frame_num]["mood"] = snap.get("mood")
        frames[frame_num]["trending"] = snap.get("trending", [])[:5]
        frames[frame_num]["snapshot"] = {
            "agent_count": snap.get("agent_count"),
            "active_agents": snap.get("active_agents"),
            "era": snap.get("era"),
            "stats": snap.get("stats"),
            "hot_channels": snap.get("hot_channels", [])[:5],
            "population": snap.get("population"),
        }

        # Pull stream activity if available
        sa = snap.get("stream_activity", {})
        if sa.get("agents_activated"):
            val = sa["agents_activated"]
            if isinstance(val, list):
                val = len(val)
            frames[frame_num]["agents_activated"] = max(
                frames[frame_num]["agents_activated"], val,
            )
        if sa.get("posts_created"):
            val = sa["posts_created"]
            if isinstance(val, list):
                val = len(val)
            frames[frame_num]["posts_count"] = max(
                frames[frame_num]["posts_count"], val,
            )
        if sa.get("comments_added"):
            val = sa["comments_added"]
            if isinstance(val, list):
                val = len(val)
            frames[frame_num]["comments_count"] = max(
                frames[frame_num]["comments_count"], val,
            )


def enrich_with_deltas(frames: dict[int, dict]) -> None:
    """Add stream delta data (frames 395-400)."""
    delta_dir = STATE_DIR / "stream_deltas"
    if not delta_dir.exists():
        return

    for f in delta_dir.glob("frame-*.json"):
        match = re.match(r"frame-(\d+)-(.+)\.json", f.name)
        if not match:
            continue

        frame_num = int(match.group(1))
        stream_id = match.group(2)

        data = json.loads(f.read_text())

        if frame_num not in frames:
            frames[frame_num] = {
                "frame": frame_num,
                "timestamp": data.get("completed_at", ""),
                "commits": [],
                "streams": [],
                "posts_count": 0,
                "comments_count": 0,
                "reactions_count": 0,
                "agents_activated": 0,
                "mood": None,
                "trending": [],
                "snapshot": None,
            }

        if stream_id not in frames[frame_num]["streams"]:
            frames[frame_num]["streams"].append(stream_id)

        posts = data.get("posts_created", [])
        comments = data.get("comments_added", [])
        reactions = data.get("reactions_added", [])

        frames[frame_num]["posts_count"] += len(posts) if isinstance(posts, list) else int(posts or 0)
        frames[frame_num]["comments_count"] += len(comments) if isinstance(comments, list) else int(comments or 0)
        frames[frame_num]["reactions_count"] += len(reactions) if isinstance(reactions, list) else int(reactions or 0)

        activated = data.get("agents_activated", [])
        if isinstance(activated, list):
            frames[frame_num]["agents_activated"] = max(
                frames[frame_num]["agents_activated"], len(activated),
            )

        # Store delta details for this frame
        if "deltas" not in frames[frame_num]:
            frames[frame_num]["deltas"] = []
        frames[frame_num]["deltas"].append({
            "stream": stream_id,
            "posts": [
                {"title": p.get("title", "")[:80], "agent": p.get("agent", ""), "discussion": p.get("discussion")}
                for p in (posts if isinstance(posts, list) else [])
            ],
            "comments": len(comments) if isinstance(comments, list) else int(comments or 0),
            "reactions": len(reactions) if isinstance(reactions, list) else int(reactions or 0),
            "agents": (activated[:10] if isinstance(activated, list) else []),
            "themes": data.get("observations", {}).get("emerging_themes", [])[:3] if isinstance(data.get("observations"), dict) else [],
        })


def correlate_posted_log(frames: dict[int, dict]) -> None:
    """Correlate posted_log entries to frames by timestamp."""
    log_path = STATE_DIR / "posted_log.json"
    if not log_path.exists():
        return

    data = json.loads(log_path.read_text())
    posts = data.get("posts", data.get("entries", []))
    if not posts:
        return

    # Build frame timestamp ranges
    sorted_frames = sorted(frames.values(), key=lambda f: f.get("timestamp", ""))
    frame_ranges = []
    for i, f in enumerate(sorted_frames):
        ts = f.get("timestamp", "")
        if not ts:
            continue
        next_ts = sorted_frames[i + 1]["timestamp"] if i + 1 < len(sorted_frames) else "9999"
        frame_ranges.append((f["frame"], ts, next_ts))

    # Count posts per frame
    for post in posts[-5000:]:  # Last 5000 posts
        post_ts = post.get("created_at", post.get("timestamp", ""))
        if not post_ts:
            continue
        for frame_num, start_ts, end_ts in frame_ranges:
            if start_ts <= post_ts < end_ts:
                if frame_num in frames:
                    frames[frame_num]["posts_count"] = frames[frame_num].get("posts_count", 0) + 1
                break


def build_timeline() -> dict:
    """Build complete frame timeline."""
    print("Extracting frames from git history...")
    frames = extract_frames_from_git()
    print(f"  Found {len(frames)} frames in git")

    print("Enriching with frame snapshots...")
    enrich_with_snapshots(frames)

    print("Enriching with stream deltas...")
    enrich_with_deltas(frames)

    # Get current frame
    fc_path = STATE_DIR / "frame_counter.json"
    current_frame = 0
    if fc_path.exists():
        fc = json.loads(fc_path.read_text())
        current_frame = fc.get("frame", 0)

    # Sort by frame number and convert to list
    frame_list = []
    for fn in sorted(frames.keys()):
        f = frames[fn]
        # Clean up: cap commit list to save space
        if len(f.get("commits", [])) > 5:
            f["commits"] = f["commits"][:5]
        frame_list.append(f)

    # Determine coverage
    frame_nums = sorted(frames.keys())
    delta_frames = [fn for fn in frame_nums if frames[fn].get("deltas")]
    snapshot_frames = [fn for fn in frame_nums if frames[fn].get("snapshot")]

    timeline = {
        "_meta": {
            "total_frames": current_frame,
            "frames_found": len(frames),
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "coverage": {
                "git_history": [min(frame_nums), max(frame_nums)] if frame_nums else [0, 0],
                "snapshots": [min(snapshot_frames), max(snapshot_frames)] if snapshot_frames else [0, 0],
                "full_deltas": [min(delta_frames), max(delta_frames)] if delta_frames else [0, 0],
            },
        },
        "frames": frame_list,
    }

    return timeline


def main() -> None:
    """Build and save frame timeline."""
    timeline = build_timeline()

    out_path = STATE_DIR / "frame_timeline.json"
    out_path.write_text(json.dumps(timeline, indent=2, ensure_ascii=False))

    meta = timeline["_meta"]
    print(f"\nSaved {out_path}")
    print(f"  Total frames: {meta['total_frames']}")
    print(f"  Frames found: {meta['frames_found']}")
    print(f"  Git history: {meta['coverage']['git_history']}")
    print(f"  Snapshots: {meta['coverage']['snapshots']}")
    print(f"  Full deltas: {meta['coverage']['full_deltas']}")


if __name__ == "__main__":
    main()
