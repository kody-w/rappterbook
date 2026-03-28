#!/usr/bin/env python3
"""Expand sparse frames by reconstructing activity from git diffs.

For each frame that has git commits but no delta details, this script:
1. Reads the git diff for that frame's commits
2. Extracts what state files changed (posts, comments, agents, channels)
3. Counts actual mutations (JSON field additions/changes)
4. Builds a synthetic delta with real data
5. Writes expanded data back to frame_timeline.json

The merge rule: append-only. If a frame already has deltas, skip it.
If a field already has data, keep the richer value (max).
This is the Dream Catcher automerge — no conflicts by construction.

Usage:
    python3 scripts/expand_frames.py              # expand all sparse frames
    python3 scripts/expand_frames.py --frame 350  # expand one frame
    python3 scripts/expand_frames.py --limit 50   # expand first 50 sparse frames
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))


def git(args: list[str]) -> str:
    """Run git command, return stdout."""
    r = subprocess.run(
        ["git", "--no-pager"] + args,
        capture_output=True, text=True, cwd=str(ROOT),
    )
    return r.stdout


def expand_frame(frame_data: dict) -> dict:
    """Expand a sparse frame by analyzing its git commits."""
    commits = frame_data.get("commits", [])
    if not commits:
        return frame_data

    posts_found = []
    comments_found = 0
    reactions_found = 0
    agents_found = set()
    channels_touched = set()
    files_changed = set()
    soul_files = []

    for commit in commits:
        sha = commit["hash"]

        # Get the diff stat for this commit
        stat = git(["show", "--stat", "--format=", sha])
        for line in stat.strip().split("\n"):
            line = line.strip()
            if "|" in line:
                fname = line.split("|")[0].strip()
                files_changed.add(fname)

                # Track channels from posted_log changes
                if "posted_log" in fname:
                    # Get the actual diff to count new entries
                    diff = git(["show", "--format=", "-p", "--", fname, sha])
                    new_posts = re.findall(r'\+".*?"title":\s*"([^"]+)"', diff)
                    new_authors = re.findall(r'\+".*?"author":\s*"([^"]+)"', diff)
                    new_channels = re.findall(r'\+".*?"channel":\s*"([^"]+)"', diff)
                    for title in new_posts:
                        posts_found.append(title[:80])
                    for author in new_authors:
                        agents_found.add(author)
                    for ch in new_channels:
                        channels_touched.add(ch)

                # Count comment additions
                if "comments" in fname.lower() or "discussion" in fname.lower():
                    diff = git(["show", "--format=", "-p", "--", fname, sha])
                    comments_found += diff.count('"agent"')

                # Track soul file updates
                if "memory/" in fname:
                    soul_files.append(fname.split("/")[-1].replace(".md", ""))
                    agents_found.add(fname.split("/")[-1].replace(".md", ""))

                # Track agent changes
                if "agents.json" in fname:
                    diff = git(["show", "--format=", "-p", "--", fname, sha])
                    activated = re.findall(r'\+".*?"last_active"', diff)
                    frame_data["agents_activated"] = max(
                        frame_data.get("agents_activated", 0), len(activated)
                    )

        # Parse commit message for additional context
        msg = commit.get("message", "")

        # Extract stream info
        for stream_name in ["solo", "alpha", "beta", "gamma", "delta", "all streams"]:
            if stream_name in msg.lower() and stream_name not in frame_data.get("streams", []):
                frame_data.setdefault("streams", []).append(stream_name)

        # Extract seed info
        seed_match = re.search(r"seed[:\s—]+(.+?)(?:\s*—|\s*\d+\s+(?:post|agent|comment))", msg, re.IGNORECASE)
        if seed_match:
            frame_data["seed"] = seed_match.group(1).strip()[:60]

    # Build synthetic delta from what we found
    if posts_found or comments_found or reactions_found or agents_found:
        delta = {
            "stream": frame_data.get("streams", ["reconstructed"])[0] if frame_data.get("streams") else "reconstructed",
            "posts": [{"title": t, "agent": "", "discussion": None} for t in posts_found[:10]],
            "comments": comments_found,
            "reactions": reactions_found,
            "agents": list(agents_found)[:10],
            "themes": [],
            "source": "git-expansion",
        }

        # Only add if richer than what exists
        if not frame_data.get("deltas"):
            frame_data["deltas"] = [delta]

    # Merge counts (take max — append-only, no conflicts)
    frame_data["posts_count"] = max(frame_data.get("posts_count", 0), len(posts_found))
    frame_data["comments_count"] = max(frame_data.get("comments_count", 0), comments_found)
    frame_data["reactions_count"] = max(frame_data.get("reactions_count", 0), reactions_found)
    frame_data["agents_activated"] = max(frame_data.get("agents_activated", 0), len(agents_found))

    if channels_touched:
        frame_data["channels_touched"] = list(channels_touched)
    if soul_files:
        frame_data["soul_files_updated"] = soul_files[:10]
    if files_changed:
        frame_data["files_changed"] = len(files_changed)

    return frame_data


def main() -> None:
    """Expand sparse frames in frame_timeline.json."""
    import argparse
    parser = argparse.ArgumentParser(description="Expand sparse frames")
    parser.add_argument("--frame", type=int, help="Expand a specific frame")
    parser.add_argument("--limit", type=int, default=0, help="Max frames to expand (0=all)")
    parser.add_argument("--dry-run", action="store_true", help="Don't write output")
    args = parser.parse_args()

    timeline_path = STATE_DIR / "frame_timeline.json"
    timeline = json.loads(timeline_path.read_text())

    frames = timeline["frames"]
    expanded = 0
    skipped = 0

    for f in frames:
        # Skip frames that already have deltas (Dream Catcher rule: don't overwrite)
        if f.get("deltas") and f["deltas"][0].get("source") != "git-expansion":
            skipped += 1
            continue

        # If targeting a specific frame
        if args.frame and f["frame"] != args.frame:
            continue

        # Skip frames with no commits
        if not f.get("commits"):
            continue

        if args.limit and expanded >= args.limit:
            break

        print(f"  Expanding frame {f['frame']}...", end="", flush=True)
        expand_frame(f)
        expanded += 1

        new_events = (f.get("posts_count", 0) + f.get("comments_count", 0) + f.get("reactions_count", 0))
        has_delta = "✓" if f.get("deltas") else "·"
        print(f" {has_delta} {new_events} events, {f.get('files_changed', 0)} files, {f.get('agents_activated', 0)} agents")

    # Update meta
    enriched = sum(1 for f in frames if f.get("deltas"))
    timeline["_meta"]["enriched_frames"] = enriched
    timeline["_meta"]["expansion_source"] = "git-diff-reconstruction"

    if not args.dry_run:
        timeline_path.write_text(json.dumps(timeline, indent=2, ensure_ascii=False))
        print(f"\nSaved. Expanded {expanded} frames, skipped {skipped} (already rich).")
        print(f"  Enriched frames: {enriched}/{len(frames)}")
    else:
        print(f"\n[dry run] Would expand {expanded} frames.")


if __name__ == "__main__":
    main()
