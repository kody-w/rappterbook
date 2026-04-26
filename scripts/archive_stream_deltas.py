#!/usr/bin/env python3
"""archive_stream_deltas — move old Dream Catcher delta files to archive/.

state/stream_deltas/ accumulates one JSON file per parallel stream per
frame. With 4–8 streams running and a frame every few minutes, the
directory grows unbounded — observed: 255 files spanning frames 500–523.

Strategy: move files for frames older than KEEP_LAST_N_FRAMES into
state/archive/stream_deltas/{frame}/{filename}. Reversible: archived
files can be moved back. The most recent frames stay where readers
expect them. Lock files (.lock) and the .gitkeep marker are skipped.

Usage:
    python scripts/archive_stream_deltas.py              # live archive
    python scripts/archive_stream_deltas.py --dry-run    # preview only
    python scripts/archive_stream_deltas.py --keep 3     # keep last 3 frames

Env vars:
    STATE_DIR              defaults to state/
    DELTA_KEEP_FRAMES      defaults to 7 (CLI --keep wins)
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_io import load_json, now_iso  # type: ignore


STATE_DIR = Path(os.environ.get("STATE_DIR", "state")).resolve()
DELTA_DIR = STATE_DIR / "stream_deltas"
ARCHIVE_DIR = STATE_DIR / "archive" / "stream_deltas"
FRAME_RE = re.compile(r"^frame-(\d+)")  # only match numeric frame ids


def current_frame() -> int:
    """Read the current frame from state/frame_counter.json (best-effort)."""
    fc = load_json(STATE_DIR / "frame_counter.json")
    return int(fc.get("frame", 0)) or _max_frame_in_dir()


def _max_frame_in_dir() -> int:
    """Fallback: highest frame number observed in the deltas dir."""
    highest = 0
    if not DELTA_DIR.is_dir():
        return 0
    for p in DELTA_DIR.glob("frame-*.json"):
        m = FRAME_RE.match(p.name)
        if m:
            try:
                highest = max(highest, int(m.group(1)))
            except ValueError:
                continue
    return highest


def find_archivable(keep_frames: int, current: int) -> list[tuple[Path, int]]:
    """Return (file, frame) pairs older than `current - keep_frames`.

    Files whose frame can't be parsed (e.g. frame-20260416-...) are
    treated as ancient and archived.
    """
    if not DELTA_DIR.is_dir():
        return []
    cutoff = current - keep_frames
    out: list[tuple[Path, int]] = []
    for p in DELTA_DIR.iterdir():
        if not p.is_file():
            continue
        if p.name == ".gitkeep" or p.suffix == ".lock":
            continue
        m = FRAME_RE.match(p.name)
        if m:
            try:
                frame = int(m.group(1))
            except ValueError:
                frame = 0
        else:
            frame = 0  # unparseable = ancient
        if frame < cutoff or (frame == 0 and current > 0):
            out.append((p, frame))
    return out


def archive(files: list[tuple[Path, int]], dry_run: bool) -> dict:
    """Move each file to archive/stream_deltas/frame-NNN/ (or .../legacy/)."""
    moved = 0
    skipped = 0
    if not dry_run:
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    for path, frame in files:
        bucket = ARCHIVE_DIR / (f"frame-{frame:04d}" if frame > 0 else "legacy")
        if dry_run:
            print(f"  DRY: would move {path.name} -> archive/stream_deltas/{bucket.name}/")
            continue
        try:
            bucket.mkdir(parents=True, exist_ok=True)
            target = bucket / path.name
            # If a file with the same name already lives in the archive (e.g.
            # a previous archive run), keep both by suffixing with the path's
            # mtime — never silently overwrite archived data.
            if target.exists():
                target = bucket / f"{path.stem}.dup-{int(path.stat().st_mtime)}{path.suffix}"
            path.rename(target)
            moved += 1
        except OSError as exc:
            print(f"  FAILED to archive {path.name}: {exc}")
            skipped += 1
    return {"moved": moved, "skipped": skipped, "candidates": len(files)}


def main() -> int:
    args = sys.argv[1:]
    dry_run = "--dry-run" in args

    keep = int(os.environ.get("DELTA_KEEP_FRAMES", "7"))
    for i, a in enumerate(args):
        if a == "--keep" and i + 1 < len(args):
            try:
                keep = int(args[i + 1])
            except ValueError:
                pass

    current = current_frame()
    candidates = find_archivable(keep, current)
    print(f"[archive_stream_deltas] current frame={current}, keep last {keep}, "
          f"candidates={len(candidates)}, dry_run={dry_run}")
    if not candidates:
        print("  nothing to archive")
        return 0

    result = archive(candidates, dry_run)
    print(f"  moved={result['moved']} skipped={result['skipped']} candidates={result['candidates']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
