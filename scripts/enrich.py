#!/usr/bin/env python3
from __future__ import annotations
"""Retroactive frame enrichment — past frames grow richer over time.

Appends observations to historical frames without modifying the original
data. Enrichments are keyed by (frame, observed_at) and are causally
consistent — they cannot contradict downstream history.

Usage:
    python scripts/enrich.py frame 200 "Pattern: agent-07's drift started here"
    python scripts/enrich.py scan              # auto-enrich from recent patterns
    python scripts/enrich.py list 200          # show enrichments for frame 200
    python scripts/enrich.py stats             # show enrichment statistics
"""
import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from state_io import load_json, now_iso, append_event

STATE_DIR = Path(os.environ.get("STATE_DIR", REPO / "state"))
ENRICHMENTS_FILE = STATE_DIR / "enrichments.jsonl"


# ---------------------------------------------------------------------------
# Core I/O
# ---------------------------------------------------------------------------

def _append_enrichment(enrichment: dict) -> None:
    """Append a single enrichment line to the JSONL store."""
    ENRICHMENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(ENRICHMENTS_FILE, "a") as f:
        f.write(json.dumps(enrichment, separators=(",", ":")) + "\n")


def _read_enrichments() -> list[dict]:
    """Read all enrichments from the JSONL store."""
    if not ENRICHMENTS_FILE.exists():
        return []
    entries = []
    with open(ENRICHMENTS_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_frame(args: argparse.Namespace) -> None:
    """Manually enrich a specific frame with an observation."""
    enrichment = {
        "frame": args.number,
        "observed_at": now_iso(),
        "source": "manual",
        "data": args.observation,
    }
    _append_enrichment(enrichment)
    append_event(
        "enrichment.added",
        frame=args.number,
        data={"source": "manual", "observation": args.observation[:200]},
        state_dir=STATE_DIR,
    )
    print(f"Enriched frame {args.number}: {args.observation[:80]}")


def cmd_scan(args: argparse.Namespace) -> None:
    """Auto-detect patterns across recent frame snapshots and enrich them."""
    snapshots_data = load_json(STATE_DIR / "frame_snapshots.json")
    snapshots = snapshots_data.get("snapshots", [])

    if not snapshots:
        print("No frame snapshots found — nothing to scan.")
        return

    # Take the last 20 snapshots
    recent = snapshots[-20:]

    # Build a summary for the LLM
    summary_lines = []
    for snap in recent:
        frame = snap.get("frame", "?")
        ts = snap.get("timestamp", "?")[:19]
        mood = snap.get("mood", "?")
        activity = snap.get("stream_activity", {})
        posts = activity.get("total_posts_created", 0)
        comments = activity.get("total_comments_added", 0)
        agents = activity.get("total_agents_activated", 0)
        summary_lines.append(
            f"Frame {frame} ({ts}): mood={mood}, "
            f"agents={agents}, posts={posts}, comments={comments}"
        )

    summary = "\n".join(summary_lines)

    # Try LLM analysis
    try:
        from github_llm import generate
        llm_prompt = (
            "Looking at these frame snapshots from a social simulation, "
            "identify patterns that span multiple frames. What started in "
            "one frame and became visible later? What trends, shifts, or "
            "emergent behaviors do you see?\n\n"
            "For each pattern found, output a JSON array of objects with:\n"
            '  {"frame": <number where pattern started>, "data": "<description>"}\n\n'
            "Output ONLY the JSON array, no other text.\n\n"
            f"Snapshots:\n{summary}"
        )
        raw = generate(
            system="You are a simulation analyst. Output valid JSON only.",
            user=llm_prompt,
            max_tokens=500,
            temperature=0.5,
        )

        # Parse the LLM output
        # Strip markdown code fences if present
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

        patterns = json.loads(cleaned)
        if not isinstance(patterns, list):
            patterns = [patterns]

        written = 0
        for pattern in patterns:
            frame_num = pattern.get("frame")
            data_text = pattern.get("data", "")
            if frame_num is None or not data_text:
                continue
            enrichment = {
                "frame": int(frame_num),
                "observed_at": now_iso(),
                "source": "auto_scan",
                "data": data_text,
            }
            _append_enrichment(enrichment)
            append_event(
                "enrichment.added",
                frame=int(frame_num),
                data={"source": "auto_scan", "observation": data_text[:200]},
                state_dir=STATE_DIR,
            )
            written += 1

        print(f"Scan complete: {written} enrichments written across {len(recent)} frames.")

    except Exception as exc:
        print(f"LLM unavailable, skipping auto-scan: {exc}")


def cmd_list(args: argparse.Namespace) -> None:
    """Show all enrichments for a specific frame."""
    entries = _read_enrichments()
    matches = [e for e in entries if e.get("frame") == args.number]

    if not matches:
        print(f"No enrichments for frame {args.number}.")
        return

    print(f"Enrichments for frame {args.number} ({len(matches)} total):\n")
    for e in matches:
        ts = e.get("observed_at", "?")[:19]
        src = e.get("source", "?")
        data = e.get("data", "")
        print(f"  [{ts}] ({src}) {data}")


def cmd_stats(args: argparse.Namespace) -> None:
    """Show enrichment statistics."""
    entries = _read_enrichments()

    if not entries:
        print("No enrichments recorded yet.")
        return

    frames = {}
    sources = {}
    for e in entries:
        frame = e.get("frame", 0)
        frames[frame] = frames.get(frame, 0) + 1
        src = e.get("source", "unknown")
        sources[src] = sources.get(src, 0) + 1

    most_enriched = max(frames, key=frames.get)

    print(f"Total enrichments: {len(entries)}")
    print(f"Frames enriched:   {len(frames)}")
    print(f"Most enriched:     frame {most_enriched} ({frames[most_enriched]} enrichments)")
    print(f"By source:")
    for src, count in sorted(sources.items()):
        print(f"  {src}: {count}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Retroactive frame enrichment — past frames grow richer over time",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")

    # frame N "observation"
    p_frame = sub.add_parser("frame", help="Manually enrich a frame")
    p_frame.add_argument("number", type=int, help="Frame number to enrich")
    p_frame.add_argument("observation", help="Observation text")
    p_frame.set_defaults(func=cmd_frame)

    # scan
    p_scan = sub.add_parser("scan", help="Auto-enrich from recent frame patterns")
    p_scan.set_defaults(func=cmd_scan)

    # list N
    p_list = sub.add_parser("list", help="Show enrichments for a frame")
    p_list.add_argument("number", type=int, help="Frame number")
    p_list.set_defaults(func=cmd_list)

    # stats
    p_stats = sub.add_parser("stats", help="Show enrichment statistics")
    p_stats.set_defaults(func=cmd_stats)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    args.func(args)


if __name__ == "__main__":
    main()
