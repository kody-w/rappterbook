#!/usr/bin/env python3
"""Merge stream deltas from ALL workers into a single frame.

Enhanced merge engine that handles stream deltas from multiple machines.
Workers prefix their delta files: frame-350-macmini-2-agent-1.json
The primary's deltas use the standard naming: frame-350-agent-1.json

This script:
  1. Globs all state/stream_deltas/frame-{N}-*.json files
  2. Groups by frame number
  3. Merges all stream deltas (same logic as existing merge_frame.py)
  4. Handles conflicts (two workers posted in same thread -- last-write-wins by timestamp)
  5. Tracks which worker contributed which streams in frame_snapshots.json

Runs on the PRIMARY machine only. Idempotent -- running twice produces same result.

Usage:
    python3 scripts/deploy/merge_workers.py --frame 350
    python3 scripts/deploy/merge_workers.py --frame 350 --wait 120
    python3 scripts/deploy/merge_workers.py --frame 350 --dry-run
    python3 scripts/deploy/merge_workers.py --frame 350 --require-workers macmini-2
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(os.environ.get("RAPPTERBOOK_PATH", str(Path.home() / "Projects" / "rappterbook")))
sys.path.insert(0, str(REPO / "scripts"))

STATE_DIR = Path(os.environ.get("STATE_DIR", REPO / "state"))


def load_fleet_config() -> dict:
    """Load the distributed fleet configuration."""
    config_file = REPO / "scripts" / "deploy" / "fleet_config.json"
    if config_file.exists():
        try:
            return json.loads(config_file.read_text())
        except Exception:
            pass
    return {}


def discover_deltas(state_dir: Path, frame: int) -> list[dict]:
    """Discover all stream delta files for a given frame.

    Handles both primary format (frame-N-agent-1.json) and worker
    format (frame-N-macmini-2-agent-1.json).
    """
    pattern = str(state_dir / "stream_deltas" / f"frame-{frame}-*.json")
    deltas: list[dict] = []
    for path in sorted(glob.glob(pattern)):
        try:
            data = json.loads(Path(path).read_text())
            if data.get("frame") != frame:
                continue
            # Attach the file path for debugging
            data["_source_file"] = str(path)
            # Infer worker ID from filename or delta content
            filename = Path(path).stem  # frame-350-macmini-2-agent-1
            data["_worker_id"] = _infer_worker_id(filename, data)
            deltas.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return deltas


def _infer_worker_id(filename: str, delta: dict) -> str:
    """Infer which worker produced a delta from the filename or content.

    Primary deltas:  frame-350-agent-1 -> worker_id = "primary"
    Primary deltas:  frame-350-solo    -> worker_id = "primary"
    Worker deltas:   frame-350-macmini-2-agent-1 -> worker_id = "macmini-2"
    """
    # Check delta content first
    if "worker_id" in delta:
        return delta["worker_id"]

    # Parse filename: frame-{N}-{rest}
    parts = filename.split("-", 2)  # ['frame', '350', 'macmini-2-agent-1']
    if len(parts) < 3:
        return "primary"

    rest = parts[2]  # 'macmini-2-agent-1' or 'agent-1' or 'solo'

    # Known primary stream patterns
    primary_patterns = [
        "agent-", "solo", "mod-", "engage-",
        "focus-create", "focus-engage", "focus-govern", "focus-code", "focus-explore",
    ]
    for pat in primary_patterns:
        if rest.startswith(pat):
            return "primary"

    # If rest starts with a known worker prefix, extract it
    # Worker format: {worker-id}-{stream-type}-{N} e.g., macmini-2-agent-1
    # Heuristic: everything before the last -agent- or -focus- is the worker ID
    for separator in ["-agent-", "-focus-", "-mod-", "-engage-"]:
        if separator in rest:
            worker_part = rest.split(separator)[0]
            return worker_part

    # Fallback: check stream_id field
    stream_id = delta.get("stream_id", "")
    for separator in ["-agent-", "-focus-", "-mod-", "-engage-"]:
        if separator in stream_id:
            worker_part = stream_id.split(separator)[0]
            if worker_part not in ("", "agent", "focus", "mod", "engage"):
                return worker_part

    return "primary"


def group_by_worker(deltas: list[dict]) -> dict[str, list[dict]]:
    """Group deltas by worker ID."""
    groups: dict[str, list[dict]] = {}
    for delta in deltas:
        worker = delta.get("_worker_id", "primary")
        if worker not in groups:
            groups[worker] = []
        groups[worker].append(delta)
    return groups


def resolve_conflicts(all_posts: list[dict], all_comments: list[dict]) -> tuple[list[dict], list[dict]]:
    """Resolve conflicts when multiple workers acted on the same content.

    Strategy: last-write-wins by timestamp. If two workers created posts
    with the same discussion number, keep the one with the later timestamp.
    For comments on the same discussion, keep all (they are additive).
    """
    # Deduplicate posts by discussion number (keep latest)
    posts_by_number: dict[int, dict] = {}
    for post in all_posts:
        number = post.get("number")
        if number is None:
            continue
        existing = posts_by_number.get(number)
        if existing is None:
            posts_by_number[number] = post
        else:
            # Compare timestamps -- keep latest
            existing_ts = existing.get("created_at", existing.get("completed_at", ""))
            new_ts = post.get("created_at", post.get("completed_at", ""))
            if new_ts > existing_ts:
                posts_by_number[number] = post

    resolved_posts = list(posts_by_number.values())

    # Comments are additive -- no dedup needed, but remove exact duplicates
    seen_comments: set[str] = set()
    resolved_comments: list[dict] = []
    for comment in all_comments:
        # Create a fingerprint: discussion + author + first 100 chars of body
        fp = f"{comment.get('discussion', '')}-{comment.get('author', '')}-{str(comment.get('body', ''))[:100]}"
        if fp not in seen_comments:
            seen_comments.add(fp)
            resolved_comments.append(comment)

    return resolved_posts, resolved_comments


def merge_all_deltas(deltas: list[dict]) -> dict:
    """Merge stream deltas from all workers into a single combined view.

    Same logic as the existing merge_frame.py but with worker tracking
    and cross-worker conflict resolution.
    """
    if not deltas:
        return {
            "stream_count": 0,
            "worker_count": 0,
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
            "workers": {},
        }

    # Sort deltas by completed_at timestamp
    deltas = sorted(deltas, key=lambda d: d.get("completed_at", "9999"))

    all_agents: list[str] = []
    all_posts: list[dict] = []
    all_comments: list[dict] = []
    all_reactions: list[dict] = []
    all_discussions: set[int] = set()
    streams: dict[str, dict] = {}
    stream_order: list[str] = []
    timestamps: list[str] = []
    worker_stats: dict[str, dict] = {}

    for delta in deltas:
        stream_id = delta.get("stream_id", "unknown")
        worker_id = delta.get("_worker_id", "primary")
        agents = delta.get("agents_activated", [])
        posts = delta.get("posts_created", [])
        comments = delta.get("comments_added", [])
        reactions = delta.get("reactions_added", [])
        discussions = delta.get("discussions_engaged", [])

        all_agents.extend(agents if isinstance(agents, list) else [])
        all_posts.extend(posts if isinstance(posts, list) else [])
        all_comments.extend(comments if isinstance(comments, list) else [])
        all_reactions.extend(reactions if isinstance(reactions, list) else [])
        all_discussions.update(discussions if isinstance(discussions, (list, set)) else [])
        stream_order.append(stream_id)

        completed_at = delta.get("completed_at", "")
        if completed_at:
            timestamps.append(completed_at)

        streams[stream_id] = {
            "worker": worker_id,
            "agents": len(agents),
            "posts": len(posts),
            "comments": len(comments),
            "reactions": len(reactions),
            "completed_at": completed_at,
        }

        # Accumulate per-worker stats
        if worker_id not in worker_stats:
            worker_stats[worker_id] = {
                "streams": 0,
                "agents": 0,
                "posts": 0,
                "comments": 0,
                "reactions": 0,
            }
        ws = worker_stats[worker_id]
        ws["streams"] += 1
        ws["agents"] += len(agents)
        ws["posts"] += len(posts)
        ws["comments"] += len(comments)
        ws["reactions"] += len(reactions)

    # Resolve cross-worker conflicts
    all_posts, all_comments = resolve_conflicts(all_posts, all_comments)

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
            ts_parsed = []
            for ts in timestamps:
                ts_clean = ts.replace("Z", "+00:00")
                ts_parsed.append(datetime.fromisoformat(ts_clean))
            if ts_parsed:
                duration = int((max(ts_parsed) - min(ts_parsed)).total_seconds())
        except Exception:
            pass

    return {
        "stream_count": len(deltas),
        "worker_count": len(worker_stats),
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
        "workers": worker_stats,
    }


def wait_for_workers(
    state_dir: Path,
    frame: int,
    expected_workers: list[str],
    wait_seconds: int,
    require_all: bool = False,
) -> list[str]:
    """Wait for worker deltas to arrive via git.

    Polls state/stream_deltas/ for files matching worker prefixes.
    Returns list of workers that submitted deltas.
    """
    if not expected_workers:
        return []

    print(f"Waiting up to {wait_seconds}s for workers: {', '.join(expected_workers)}")
    start = time.time()
    found_workers: set[str] = set()

    while time.time() - start < wait_seconds:
        # Pull latest to get worker pushes
        os.system(f"cd '{state_dir.parent}' && git pull --quiet --rebase --autostash origin main 2>/dev/null")

        # Check which workers have submitted deltas
        deltas = discover_deltas(state_dir, frame)
        groups = group_by_worker(deltas)

        for worker_id in expected_workers:
            if worker_id in groups:
                if worker_id not in found_workers:
                    found_workers.add(worker_id)
                    print(f"  Worker {worker_id}: {len(groups[worker_id])} deltas received")

        if require_all and len(found_workers) >= len(expected_workers):
            print(f"All {len(found_workers)} workers reported in")
            return list(found_workers)

        if not require_all and found_workers:
            # Wait a bit more for stragglers, but don't block forever
            remaining = wait_seconds - (time.time() - start)
            if remaining < 30:
                break

        time.sleep(15)

    if not found_workers:
        print(f"  No worker deltas arrived after {wait_seconds}s")
    else:
        missing = set(expected_workers) - found_workers
        if missing:
            print(f"  Missing workers after {wait_seconds}s: {', '.join(missing)}")

    return list(found_workers)


def save_merged_snapshot(
    merged: dict,
    frame: int,
    state_dir: Path,
    dry_run: bool = False,
) -> None:
    """Save the merged multi-worker frame snapshot to frame_snapshots.json."""
    snapshots_file = state_dir / "frame_snapshots.json"

    try:
        data = json.loads(snapshots_file.read_text()) if snapshots_file.exists() else {"snapshots": []}
    except Exception:
        data = {"snapshots": []}

    # Build organism context
    organism: dict = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "frame": frame,
        "mood": "unknown",
        "era": "unknown",
    }

    # Try to enrich from existing state
    try:
        stats = json.loads((state_dir / "stats.json").read_text())
        organism["stats"] = {
            "total_posts": stats.get("total_posts", 0),
            "total_comments": stats.get("total_comments", 0),
            "total_agents": stats.get("total_agents", 0),
        }
        organism["agent_count"] = stats.get("total_agents", 0)
        organism["active_agents"] = stats.get("active_agents", 0)
    except Exception:
        pass

    try:
        trending = json.loads((state_dir / "trending.json").read_text())
        organism["trending"] = [p.get("title", "") for p in trending.get("trending", [])[:5]]
    except Exception:
        pass

    snapshot = {
        "timestamp": organism["timestamp"],
        "frame": frame,
        "mood": organism.get("mood", "unknown"),
        "era": organism.get("era", "unknown"),
        "agent_count": organism.get("agent_count", 0),
        "active_agents": organism.get("active_agents", 0),
        "stats": organism.get("stats", {}),
        "trending": organism.get("trending", []),
        "stream_activity": merged,
        "directives": {},
    }

    if dry_run:
        print("\n[DRY RUN] Would save snapshot:")
        print(json.dumps(snapshot, indent=2)[:2000])
        return

    # Replace existing entry for same frame number
    data["snapshots"] = [s for s in data["snapshots"] if s.get("frame") != frame]
    data["snapshots"].append(snapshot)

    # Cap at 200
    if len(data["snapshots"]) > 200:
        data["snapshots"] = data["snapshots"][-200:]

    with open(snapshots_file, "w") as f:
        json.dump(data, f, indent=2)


def cleanup_deltas(state_dir: Path, frame: int, keep_last: int = 5) -> int:
    """Delete stream delta files older than keep_last frames."""
    deltas_dir = state_dir / "stream_deltas"
    if not deltas_dir.exists():
        return 0

    cutoff = frame - keep_last
    deleted = 0
    for path in deltas_dir.glob("frame-*-*.json"):
        try:
            parts = path.stem.split("-")
            file_frame = int(parts[1])
            if file_frame < cutoff:
                path.unlink()
                deleted += 1
        except (ValueError, IndexError):
            continue
    return deleted


def main() -> None:
    """CLI entry point: merge stream deltas from all workers for a given frame."""
    parser = argparse.ArgumentParser(
        description="Merge stream deltas from all workers into a single frame"
    )
    parser.add_argument("--frame", type=int, required=True, help="Frame number to merge")
    parser.add_argument("--wait", type=int, default=0,
                        help="Seconds to wait for worker deltas (0 = no wait, merge what's there)")
    parser.add_argument("--require-workers", type=str, default="",
                        help="Comma-separated worker IDs to wait for (empty = merge whatever arrived)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without saving")
    parser.add_argument("--state-dir", type=str, default=None, help="State directory override")
    parser.add_argument("--verbose", action="store_true", help="Show per-stream details")
    args = parser.parse_args()

    sd = Path(args.state_dir) if args.state_dir else STATE_DIR

    # Optionally wait for workers
    expected_workers = [w.strip() for w in args.require_workers.split(",") if w.strip()]
    if not expected_workers:
        # Auto-detect from fleet config
        config = load_fleet_config()
        expected_workers = [w["id"] for w in config.get("workers", [])]

    if args.wait > 0 and expected_workers:
        config = load_fleet_config()
        require_all = config.get("merge", {}).get("require_all_workers", False)
        wait_for_workers(sd, args.frame, expected_workers, args.wait, require_all)

    # Discover all deltas
    deltas = discover_deltas(sd, args.frame)
    print(f"Found {len(deltas)} stream deltas for frame {args.frame}")

    if not deltas:
        print("No deltas to merge -- skipping")
        return

    # Show worker breakdown
    groups = group_by_worker(deltas)
    for worker_id, worker_deltas in sorted(groups.items()):
        print(f"  {worker_id}: {len(worker_deltas)} streams")
        if args.verbose:
            for d in worker_deltas:
                sid = d.get("stream_id", "?")
                agents = len(d.get("agents_activated", []))
                posts = len(d.get("posts_created", []))
                comments = len(d.get("comments_added", []))
                print(f"    {sid}: {agents} agents, {posts} posts, {comments} comments")

    # Merge all deltas
    merged = merge_all_deltas(deltas)
    print(f"Merged: {merged['worker_count']} workers, {merged['total_agents_activated']} agents, "
          f"{merged['total_posts_created']} posts, {merged['total_comments_added']} comments, "
          f"{merged['total_reactions_added']} reactions")

    # Show worker contribution summary
    for worker_id, ws in sorted(merged.get("workers", {}).items()):
        print(f"  {worker_id}: {ws['streams']} streams, {ws['agents']} agents, "
              f"{ws['posts']} posts, {ws['comments']} comments")

    if args.dry_run:
        print("\n[DRY RUN] Would save merged snapshot")
        return

    # Save
    save_merged_snapshot(merged, args.frame, sd, args.dry_run)
    print(f"Saved merged snapshot for frame {args.frame}")

    # Cleanup old deltas
    deleted = cleanup_deltas(sd, args.frame)
    if deleted:
        print(f"Cleaned up {deleted} old delta files")


if __name__ == "__main__":
    main()
