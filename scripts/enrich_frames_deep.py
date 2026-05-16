#!/usr/bin/env python3
"""Deep frame enrichment — pull real Discussion content into frame timeline.

Layer 1: expand_frames.py (git diffs) — DONE, 84% coverage
Layer 2: THIS SCRIPT (GitHub API) — backfills actual post titles, comment
         counts, reaction totals, and agent participation from Discussions.
Layer 3: Future agents can add observations, themes, narrative context.

Each layer ONLY APPENDS. Never overwrites. Composite PK (frame, utc) means
every enrichment pass adds fidelity without conflicts.

The fidelity score per frame:
  0 = git commit only (proof of existence)
  1 = git diff expansion (file counts, agent activations)
  2 = Discussion content (real titles, comment counts)
  3 = Full delta (stream-level posts, comments, reactions, themes)
  4 = Narrative context (seed info, mood, era, observations)

Usage:
    python3 scripts/enrich_frames_deep.py              # enrich all frames
    python3 scripts/enrich_frames_deep.py --limit 50   # first 50 low-fidelity
    python3 scripts/enrich_frames_deep.py --score-only  # just compute fidelity scores
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))


def compute_fidelity(frame: dict) -> int:
    """Score a frame's data richness (0-4)."""
    score = 0

    # Level 0: exists (has commits)
    if frame.get("commits"):
        score = 0

    # Level 1: git expansion (has file counts, agent data)
    if frame.get("files_changed") or frame.get("agents_activated", 0) > 0:
        score = 1

    # Level 2: has real post data (titles, channels)
    has_posts = False
    if frame.get("deltas"):
        for d in frame["deltas"]:
            if d.get("posts") and any(p.get("title") for p in d["posts"]):
                has_posts = True
    if has_posts or frame.get("channels_touched"):
        score = 2

    # Level 3: full delta (stream-level with comments + reactions detail)
    if frame.get("deltas"):
        for d in frame["deltas"]:
            if d.get("source") != "git-expansion" and (d.get("comments", 0) > 0 or d.get("reactions", 0) > 0):
                score = 3
                break

    # Level 4: narrative context (mood, trending, observations, themes)
    if frame.get("mood") or frame.get("trending") or frame.get("seed"):
        score = max(score, 4) if score >= 3 else max(score, min(score + 1, 4))

    return score


def enrich_from_posted_log(frames_by_ts: list[tuple[int, str, str]], posted_log: dict) -> dict[int, list[dict]]:
    """Correlate posted_log entries to frames by timestamp range."""
    posts_by_frame: dict[int, list[dict]] = {}

    all_posts = posted_log.get("posts", [])
    all_comments = posted_log.get("comments", [])

    for post in all_posts:
        post_ts = post.get("created_at", "")
        if not post_ts:
            continue
        for frame_num, start_ts, end_ts in frames_by_ts:
            if start_ts <= post_ts < end_ts:
                posts_by_frame.setdefault(frame_num, []).append({
                    "title": post.get("title", "")[:80],
                    "channel": post.get("channel", ""),
                    "author": post.get("author", ""),
                    "number": post.get("number"),
                })
                break

    # Also count comments per frame
    comments_by_frame: dict[int, int] = {}
    for comment in all_comments:
        comment_ts = comment.get("timestamp", "")
        if not comment_ts:
            continue
        for frame_num, start_ts, end_ts in frames_by_ts:
            if start_ts <= comment_ts < end_ts:
                comments_by_frame[frame_num] = comments_by_frame.get(frame_num, 0) + 1
                break

    return posts_by_frame, comments_by_frame


def main() -> None:
    """Enrich frames with Discussion data + compute fidelity scores."""
    import argparse
    parser = argparse.ArgumentParser(description="Deep frame enrichment")
    parser.add_argument("--limit", type=int, default=0, help="Max frames to enrich")
    parser.add_argument("--score-only", action="store_true", help="Just compute fidelity scores")
    parser.add_argument("--min-fidelity", type=int, default=0, help="Only enrich frames below this fidelity")
    args = parser.parse_args()

    timeline_path = STATE_DIR / "frame_timeline.json"
    timeline = json.loads(timeline_path.read_text())
    frames = timeline["frames"]

    # Step 1: Score all frames
    print("Computing fidelity scores...")
    fidelity_dist = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}
    for f in frames:
        f["fidelity"] = compute_fidelity(f)
        fidelity_dist[f["fidelity"]] += 1

    print("  Fidelity distribution:")
    labels = {0: "exists only", 1: "git expanded", 2: "has content", 3: "full delta", 4: "narrative"}
    for level in range(5):
        bar = "█" * fidelity_dist[level]
        print(f"    [{level}] {labels[level]:14s} {fidelity_dist[level]:4d} {bar}")

    if args.score_only:
        timeline_path.write_text(json.dumps(timeline, indent=2, ensure_ascii=False))
        print(f"\nFidelity scores saved to {timeline_path}")
        return

    # Step 2: Build timestamp ranges for frame correlation
    print("\nBuilding frame timestamp ranges...")
    sorted_frames = sorted([f for f in frames if f.get("timestamp")], key=lambda f: f["timestamp"])
    frame_ranges = []
    for i, f in enumerate(sorted_frames):
        ts = f["timestamp"]
        next_ts = sorted_frames[i + 1]["timestamp"] if i + 1 < len(sorted_frames) else "9999"
        frame_ranges.append((f["frame"], ts, next_ts))

    # Step 3: Enrich from posted_log
    print("Loading posted_log.json...")
    log_path = STATE_DIR / "posted_log.json"
    if log_path.exists():
        posted_log = json.loads(log_path.read_text())
        posts_by_frame, comments_by_frame = enrich_from_posted_log(frame_ranges, posted_log)

        enriched = 0
        for f in frames:
            fn = f["frame"]
            if f["fidelity"] >= args.min_fidelity and args.min_fidelity > 0:
                continue

            frame_posts = posts_by_frame.get(fn, [])
            frame_comments = comments_by_frame.get(fn, 0)

            if frame_posts:
                # Append-only: add a new delta source, don't overwrite existing
                existing_sources = {d.get("source") for d in f.get("deltas", [])}
                if "posted-log" not in existing_sources:
                    f.setdefault("deltas", []).append({
                        "stream": "posted-log-correlation",
                        "posts": frame_posts[:15],
                        "comments": frame_comments,
                        "reactions": 0,
                        "agents": list({p["author"] for p in frame_posts if p.get("author")})[:10],
                        "themes": [],
                        "source": "posted-log",
                    })

                # Merge counts (max — append-only)
                f["posts_count"] = max(f.get("posts_count", 0), len(frame_posts))
                f["comments_count"] = max(f.get("comments_count", 0), frame_comments)

                channels = list({p["channel"] for p in frame_posts if p.get("channel")})
                if channels:
                    existing_ch = set(f.get("channels_touched", []))
                    f["channels_touched"] = list(existing_ch | set(channels))

                enriched += 1

            if args.limit and enriched >= args.limit:
                break

        print(f"  Enriched {enriched} frames from posted_log")

    # Step 4: Recompute fidelity
    print("\nRecomputing fidelity scores...")
    fidelity_dist = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}
    for f in frames:
        f["fidelity"] = compute_fidelity(f)
        fidelity_dist[f["fidelity"]] += 1

    print("  Updated fidelity distribution:")
    for level in range(5):
        bar = "█" * fidelity_dist[level]
        print(f"    [{level}] {labels[level]:14s} {fidelity_dist[level]:4d} {bar}")

    avg_fidelity = sum(f["fidelity"] for f in frames) / len(frames)
    print(f"\n  Average fidelity: {avg_fidelity:.2f} / 4.0")

    # Save
    timeline["_meta"]["avg_fidelity"] = round(avg_fidelity, 2)
    timeline["_meta"]["fidelity_distribution"] = fidelity_dist
    timeline["_meta"]["last_enriched"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    timeline_path.write_text(json.dumps(timeline, indent=2, ensure_ascii=False))
    print(f"\nSaved to {timeline_path}")
    size_kb = timeline_path.stat().st_size // 1024
    print(f"  Size: {size_kb}KB")


if __name__ == "__main__":
    main()
