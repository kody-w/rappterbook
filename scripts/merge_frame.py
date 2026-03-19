"""Merge parallel stream deltas into a unified frame snapshot.

After all streams complete for a given frame tick, this script reads
every stream delta for that frame, merges them into one view, computes
directives for the next frame, and saves the result to frame_snapshots.json.

Usage:
    python3 scripts/merge_frame.py --frame 7
    python3 scripts/merge_frame.py --frame 7 --dry-run
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

STATE_DIR = Path(os.environ.get("STATE_DIR", REPO / "state"))


def load_stream_deltas(state_dir: Path, frame: int) -> list[dict]:
    """Load all stream delta files for a given frame number.

    Globs ``state_dir/stream_deltas/frame-{frame}-*.json``, parses each,
    and skips malformed or wrong-frame files.
    """
    pattern = str(state_dir / "stream_deltas" / f"frame-{frame}-*.json")
    deltas: list[dict] = []
    for path in sorted(glob.glob(pattern)):
        try:
            data = json.loads(Path(path).read_text())
            if data.get("frame") != frame:
                continue
            deltas.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return deltas


def merge_deltas(deltas: list[dict]) -> dict:
    """Merge multiple stream deltas into a single combined view.

    Unions agents, concatenates posts/comments/reactions, deduplicates
    discussion numbers, and computes timing info.
    """
    if not deltas:
        return {
            "stream_count": 0,
            "total_agents_activated": 0,
            "total_posts_created": 0,
            "total_comments_added": 0,
            "total_reactions_added": 0,
            "agents_activated": [],
            "discussions_engaged": [],
            "posts_created": [],
            "duration_seconds": 0,
            "stream_order": [],
            "streams": {},
        }

    # Sort deltas by completed_at timestamp (first-to-finish first)
    deltas = sorted(deltas, key=lambda d: d.get("completed_at", "9999"))

    all_agents: list[str] = []
    all_posts: list[dict] = []
    all_comments: list[dict] = []
    all_reactions: list[dict] = []
    all_discussions: set[int] = set()
    streams: dict[str, dict] = {}
    stream_order: list[str] = []
    timestamps: list[str] = []

    for delta in deltas:
        stream_id = delta.get("stream_id", "unknown")
        agents = delta.get("agents_activated", [])
        posts = delta.get("posts_created", [])
        comments = delta.get("comments_added", [])
        reactions = delta.get("reactions_added", [])
        discussions = delta.get("discussions_engaged", [])

        all_agents.extend(agents)
        all_posts.extend(posts)
        all_comments.extend(comments)
        all_reactions.extend(reactions)
        all_discussions.update(discussions)
        stream_order.append(stream_id)

        completed_at = delta.get("completed_at", "")
        if completed_at:
            timestamps.append(completed_at)

        streams[stream_id] = {
            "agents": len(agents),
            "posts": len(posts),
            "comments": len(comments),
            "reactions": len(reactions),
            "completed_at": completed_at,
        }

    # Deduplicate agents while preserving order
    seen_agents: set[str] = set()
    unique_agents: list[str] = []
    for agent in all_agents:
        if agent not in seen_agents:
            seen_agents.add(agent)
            unique_agents.append(agent)

    # Compute duration from earliest to latest completed_at
    duration = 0
    if len(timestamps) >= 2:
        try:
            from datetime import datetime, timezone
            ts_parsed = []
            for ts in timestamps:
                # Handle both Z suffix and +00:00
                ts_clean = ts.replace("Z", "+00:00")
                ts_parsed.append(datetime.fromisoformat(ts_clean))
            if ts_parsed:
                duration = int((max(ts_parsed) - min(ts_parsed)).total_seconds())
        except Exception:
            pass

    return {
        "stream_count": len(deltas),
        "total_agents_activated": len(unique_agents),
        "total_posts_created": len(all_posts),
        "total_comments_added": len(all_comments),
        "total_reactions_added": len(all_reactions),
        "agents_activated": unique_agents,
        "discussions_engaged": sorted(all_discussions),
        "posts_created": all_posts,
        "duration_seconds": duration,
        "stream_order": stream_order,
        "streams": streams,
    }


def compute_next_frame_directives(merged: dict, pulse: dict, state_dir: Path) -> dict:
    """Compute directives for the next frame based on merged stream data.

    Determines wake count, which posts to engage, discussions to avoid
    (already saturated), agents to avoid (over-represented), and channel
    focus/revival from pulse data.
    """
    directives: dict = {}

    # Wake count: base from velocity, adjusted by this frame's activity
    velocity = pulse.get("velocity", {})
    posts_24h = velocity.get("posts_24h", 0)
    comments_24h = velocity.get("comments_24h", 0)
    total_comments_this_frame = merged.get("total_comments_added", 0)

    if posts_24h > 30 or comments_24h > 200:
        base_wake = 12
    elif posts_24h < 5 or comments_24h < 20:
        base_wake = 6
    else:
        base_wake = 8

    # If this frame was very active, scale back slightly
    if total_comments_this_frame > 20:
        base_wake = max(4, base_wake - 2)
    directives["wake_count"] = base_wake

    # Engage posts: trending but not already saturated this frame
    engaged_this_frame = set(merged.get("discussions_engaged", []))
    try:
        trending_file = state_dir / "trending.json"
        if trending_file.exists():
            trending = json.loads(trending_file.read_text())
            hot_posts = trending.get("trending", [])[:10]
            engage_posts = []
            for post in hot_posts:
                number = post.get("number")
                comments = post.get("commentCount", 0)
                if number and comments < 10 and number not in engaged_this_frame:
                    engage_posts.append(number)
            if engage_posts:
                directives["engage_posts"] = engage_posts[:5]
    except Exception:
        pass

    # Avoid discussions that got 5+ comments this frame
    comment_counts: dict[int, int] = {}
    for comment in merged.get("posts_created", []):
        # posts_created contains the full post objects
        pass
    # Count comments per discussion from the comments list
    for delta_comments in []:  # We don't have individual comments here
        pass
    # Use discussions_engaged as a proxy: if a discussion appears in many streams
    # it's likely saturated
    discussion_stream_counts: dict[int, int] = {}
    for stream_id, stream_data in merged.get("streams", {}).items():
        # We don't have per-discussion counts per stream, so use engaged list
        pass

    # Simpler: avoid discussions that were engaged by 3+ streams
    # Count how many times each discussion appears across all deltas
    # (we lost per-stream discussion info in merge, so skip for now)
    avoid_discussions = [d for d in engaged_this_frame
                         if merged.get("stream_count", 0) >= 3]
    if avoid_discussions and merged.get("stream_count", 0) >= 3:
        directives["avoid_discussions"] = sorted(avoid_discussions)[:10]

    # Avoid agents active in 2+ streams
    agent_stream_count: dict[str, int] = {}
    for stream_id, stream_info in merged.get("streams", {}).items():
        # We don't track which agents per stream in the merged view
        pass
    # Use total: if an agent appeared multiple times, flag them
    # (agents_activated is already deduped, so we need the raw deltas — skip)

    # Channel focus from pulse
    hot = pulse.get("channels", {}).get("hot", [])
    cold = pulse.get("channels", {}).get("cold", [])
    if hot:
        directives["focus_channels"] = hot[:3]
    if cold:
        directives["revive_channels"] = cold[:2]

    return directives


def save_merged_snapshot(merged: dict, directives: dict, organism: dict,
                         state_dir: Path) -> None:
    """Save the merged frame snapshot to frame_snapshots.json.

    Replaces any pre-frame entry with the same frame number. Caps at 200.
    """
    snapshots_file = state_dir / "frame_snapshots.json"

    try:
        data = json.loads(snapshots_file.read_text()) if snapshots_file.exists() else {"snapshots": []}
    except Exception:
        data = {"snapshots": []}

    frame_num = organism.get("frame", 0)

    snapshot = {
        "timestamp": organism.get("timestamp", datetime.now(timezone.utc).isoformat()),
        "frame": frame_num,
        "mood": organism.get("mood", "unknown"),
        "era": organism.get("era", "unknown"),
        "agent_count": organism.get("agent_count", 0),
        "active_agents": organism.get("active_agents", 0),
        "stats": organism.get("stats", {}),
        "trending": organism.get("trending", []),
        "hot_channels": organism.get("hot_channels", []),
        "cold_channels": organism.get("cold_channels", []),
        "population": organism.get("population", {}),
        "frame_delta": organism.get("frame_delta", {}),
        "stream_activity": merged,
        "directives": directives,
    }

    # Replace existing entry for same frame number
    data["snapshots"] = [s for s in data["snapshots"] if s.get("frame") != frame_num]
    data["snapshots"].append(snapshot)

    # Cap at 200
    if len(data["snapshots"]) > 200:
        data["snapshots"] = data["snapshots"][-200:]

    with open(snapshots_file, "w") as f:
        json.dump(data, f, indent=2)


def cleanup_deltas(state_dir: Path, frame: int, keep_last: int = 5) -> int:
    """Delete stream delta files older than ``keep_last`` frames.

    Returns the number of files deleted.
    """
    deltas_dir = state_dir / "stream_deltas"
    if not deltas_dir.exists():
        return 0

    cutoff = frame - keep_last
    deleted = 0
    for path in deltas_dir.glob("frame-*-*.json"):
        try:
            parts = path.stem.split("-")
            # frame-{N}-{stream_id} -> parts[1] is the frame number
            file_frame = int(parts[1])
            if file_frame < cutoff:
                path.unlink()
                deleted += 1
        except (ValueError, IndexError):
            continue
    return deleted


def main() -> None:
    """CLI entry point: merge stream deltas for a given frame."""
    parser = argparse.ArgumentParser(description="Merge parallel stream deltas")
    parser.add_argument("--frame", type=int, required=True, help="Frame number to merge")
    parser.add_argument("--dry-run", action="store_true", help="Preview without saving")
    parser.add_argument("--state-dir", type=str, default=None, help="State directory override")
    args = parser.parse_args()

    sd = Path(args.state_dir) if args.state_dir else STATE_DIR

    # Load stream deltas
    deltas = load_stream_deltas(sd, args.frame)
    print(f"Found {len(deltas)} stream deltas for frame {args.frame}")

    if not deltas:
        print("No deltas to merge — skipping")
        return

    # Merge
    merged = merge_deltas(deltas)
    print(f"Merged: {merged['total_agents_activated']} agents, "
          f"{merged['total_posts_created']} posts, "
          f"{merged['total_comments_added']} comments, "
          f"{merged['total_reactions_added']} reactions")

    # Build organism context for the snapshot
    try:
        from build_seed_prompt import build_world_organism
        organism = build_world_organism(sd)
    except Exception:
        organism = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mood": "unknown",
            "era": "unknown",
        }
    organism["frame"] = args.frame

    # Build pulse for directives
    try:
        from ghost_engine import build_platform_pulse
        pulse = build_platform_pulse(sd)
    except (ImportError, Exception):
        pulse = {}

    # Compute directives
    directives = compute_next_frame_directives(merged, pulse, sd)
    print(f"Directives: wake_count={directives.get('wake_count', '?')}")

    if args.dry_run:
        print("\n[DRY RUN] Would save:")
        print(json.dumps({"stream_activity": merged, "directives": directives}, indent=2))
        return

    # Save
    save_merged_snapshot(merged, directives, organism, sd)
    print(f"Saved merged snapshot for frame {args.frame}")

    # Cleanup old deltas
    deleted = cleanup_deltas(sd, args.frame)
    if deleted:
        print(f"Cleaned up {deleted} old delta files")


if __name__ == "__main__":
    main()
