#!/usr/bin/env python3
from __future__ import annotations
"""Verify L1 frame ledger structural integrity.

Exits 0 if ledger is well-formed, 1 if errors are found.

Usage
-----
    python3 scripts/verify_ledger_consistency.py             # check all frames
    python3 scripts/verify_ledger_consistency.py --frame N   # check one frame
    python3 scripts/verify_ledger_consistency.py --strict    # fail on warnings too
"""

import os
import sys
from pathlib import Path

STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))

sys.path.insert(0, str(Path(__file__).resolve().parent))
from frame_ledger import validate_ledger, list_frames, _frame_dir


def _validate_one_frame(frame_tick: int, state_dir: Path, strict: bool) -> list[str]:
    """Validate a single frame, return list of error strings."""
    from frame_ledger import list_frame_streams, _stream_path
    import json

    errors: list[str] = []
    warnings: list[str] = []

    fdir = _frame_dir(frame_tick, state_dir)
    streams_dir = fdir / "streams"

    if not streams_dir.exists():
        errors.append(f"frame {frame_tick}: missing streams/ subdirectory")
        return errors

    seen_delta_ids: set[str] = set()
    actual_delta_count = 0
    actual_stream_count = 0

    for jsonl_path in sorted(streams_dir.glob("*.jsonl")):
        stream_id = jsonl_path.stem
        actual_stream_count += 1
        prev_utc = ""

        try:
            lines = jsonl_path.read_text().splitlines()
        except OSError as exc:
            errors.append(f"frame {frame_tick}/{stream_id}.jsonl: cannot read: {exc}")
            continue

        for lineno, raw in enumerate(lines, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError as exc:
                errors.append(
                    f"frame {frame_tick}/{stream_id}.jsonl:{lineno}: invalid JSON: {exc}"
                )
                continue

            actual_delta_count += 1

            # Required fields
            for field in ("type", "utc", "source"):
                if field not in obj:
                    errors.append(
                        f"frame {frame_tick}/{stream_id}.jsonl:{lineno}: missing required field '{field}'"
                    )

            # Duplicate delta_id
            delta_id = obj.get("delta_id")
            if delta_id:
                if delta_id in seen_delta_ids:
                    errors.append(
                        f"frame {frame_tick}/{stream_id}.jsonl:{lineno}: "
                        f"duplicate delta_id '{delta_id}'"
                    )
                else:
                    seen_delta_ids.add(delta_id)

            # Monotonic UTC per stream
            utc = obj.get("utc", "")
            if prev_utc and utc and utc < prev_utc:
                msg = (
                    f"frame {frame_tick}/{stream_id}.jsonl:{lineno}: "
                    f"utc {utc!r} < previous {prev_utc!r} (non-monotonic within stream)"
                )
                if strict:
                    errors.append(msg)
                else:
                    warnings.append(msg)
            if utc:
                prev_utc = utc

    # Check meta.json accuracy if present
    meta_path = fdir / "meta.json"
    if meta_path.exists():
        try:
            import json as _json
            meta = _json.loads(meta_path.read_text())
            if meta.get("stream_count") != actual_stream_count:
                msg = (
                    f"frame {frame_tick}/meta.json: stream_count={meta.get('stream_count')} "
                    f"!= actual={actual_stream_count}"
                )
                warnings.append(msg)
            if meta.get("delta_count") != actual_delta_count:
                msg = (
                    f"frame {frame_tick}/meta.json: delta_count={meta.get('delta_count')} "
                    f"!= actual={actual_delta_count}"
                )
                warnings.append(msg)
        except Exception as exc:
            errors.append(f"frame {frame_tick}/meta.json: {exc}")

    if strict:
        return errors + warnings
    return errors


def main() -> int:
    """CLI entry point."""
    argv = sys.argv[1:]
    state_dir = Path(os.environ.get("STATE_DIR", "state"))
    strict = "--strict" in argv
    frame_filter: int | None = None

    for i, arg in enumerate(argv):
        if arg == "--frame" and i + 1 < len(argv):
            try:
                frame_filter = int(argv[i + 1])
            except ValueError:
                print(f"Invalid frame number: {argv[i + 1]}", file=sys.stderr)
                return 1

    frames = list_frames(state_dir)
    if frame_filter is not None:
        if frame_filter not in frames:
            print(f"Frame {frame_filter} not found in ledger.")
            return 1
        frames = [frame_filter]

    if not frames:
        print("Ledger is empty — no frames to validate.")
        return 0

    all_errors: list[str] = []
    for tick in frames:
        errs = _validate_one_frame(tick, state_dir, strict)
        all_errors.extend(errs)

    if not all_errors:
        print(f"Ledger OK — {len(frames)} frame(s) validated.")
        return 0

    for err in all_errors:
        print(f"ERROR: {err}", file=sys.stderr)
    print(f"\n{len(all_errors)} error(s) found in {len(frames)} frame(s).", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
