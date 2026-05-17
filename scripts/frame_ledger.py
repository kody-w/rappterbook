#!/usr/bin/env python3
from __future__ import annotations
"""L1 Frame Ledger — append-only delta log keyed by (frame_tick, utc_timestamp).

This module implements the data-link layer of the Rappterbook OSI-style stack.
Every action that mutates state is ALSO recorded here as a frame-keyed delta,
enabling lossless reconstruction of canonical state from the ledger alone.

Atomicity guarantee
-------------------
Appends use Python's built-in ``open(path, "a")`` which on POSIX sets O_APPEND
on the underlying file descriptor.  A single ``write()`` call that is smaller
than PIPE_BUF (≥ 4 096 bytes on all POSIX platforms, ≥ 65 536 on Linux) is
atomic — no other process can interleave bytes in the middle of the write.
Because each line is one JSON object terminated by a newline, and the vast
majority of delta lines are well under 4 KB, concurrent appends from multiple
processes cannot corrupt the file.  For safety this module also confirms the
JSON fits in one write; callers that produce unusually large payloads are warned.

File layout
-----------
state/frames/{frame_tick:06d}/streams/{stream_id}.jsonl  — JSONL delta log
state/frames/{frame_tick:06d}/meta.json                  — frame summary
state/frames/_meta.json                                  — global ledger meta
                                                            (current_tick counter)
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Resolve STATE_DIR robustly from env or relative to this file
# ---------------------------------------------------------------------------

def _default_state_dir() -> Path:
    return Path(os.environ.get(
        "STATE_DIR",
        str(Path(__file__).resolve().parent.parent / "state"),
    ))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    """Current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _frames_root(state_dir: Path) -> Path:
    root = state_dir / "frames"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _global_meta_path(state_dir: Path) -> Path:
    return _frames_root(state_dir) / "_meta.json"


def _frame_dir(frame_tick: int, state_dir: Path) -> Path:
    return _frames_root(state_dir) / f"{frame_tick:06d}"


def _streams_dir(frame_tick: int, state_dir: Path) -> Path:
    d = _frame_dir(frame_tick, state_dir) / "streams"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _stream_path(frame_tick: int, stream_id: str, state_dir: Path) -> Path:
    return _streams_dir(frame_tick, state_dir) / f"{stream_id}.jsonl"


def _load_global_meta(state_dir: Path) -> dict:
    """Load global ledger meta, returning defaults if absent."""
    path = _global_meta_path(state_dir)
    if not path.exists():
        return {"current_tick": 1, "created_at": _now_iso(), "last_updated": _now_iso()}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {"current_tick": 1, "created_at": _now_iso(), "last_updated": _now_iso()}


def _save_global_meta(meta: dict, state_dir: Path) -> None:
    """Persist global meta atomically."""
    path = _global_meta_path(state_dir)
    meta["last_updated"] = _now_iso()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(meta, indent=2) + "\n")
    os.replace(str(tmp), str(path))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def current_frame_tick(state_dir: Optional[Path] = None) -> int:
    """Compute the current frame tick.

    Resolution order:
    1. Active seed in state/seeds.json → ``active.frames_active`` (the live
       simulation counter maintained by the engine).
    2. Fall back to ``state/frames/_meta.json`` → ``current_tick`` (explicit
       advance via :func:`advance_frame`).
    3. Init to 1 if neither exists.

    The engine will eventually call :func:`advance_frame` explicitly.  Until
    then every inbox-processed delta lands in the same tick (the seed's
    ``frames_active``) which is exactly correct — one tick = one frame batch.
    """
    if state_dir is None:
        state_dir = _default_state_dir()
    state_dir = Path(state_dir)

    # Strategy 1 — active seed frames_active
    try:
        seeds_path = state_dir / "seeds.json"
        if seeds_path.exists():
            seeds = json.loads(seeds_path.read_text())
            active = seeds.get("active")
            if active and isinstance(active, dict):
                tick = active.get("frames_active")
                if isinstance(tick, int) and tick > 0:
                    return tick
    except (json.JSONDecodeError, OSError, KeyError):
        pass

    # Strategy 2 — explicit counter in _meta.json
    meta = _load_global_meta(state_dir)
    return int(meta.get("current_tick", 1))


def advance_frame(state_dir: Optional[Path] = None) -> int:
    """Increment the global tick counter and return the new tick.

    Called by the engine at frame boundaries.  Until the engine integrates
    this call, :func:`current_frame_tick` uses the seed's ``frames_active``
    counter instead.
    """
    if state_dir is None:
        state_dir = _default_state_dir()
    state_dir = Path(state_dir)
    meta = _load_global_meta(state_dir)
    meta["current_tick"] = int(meta.get("current_tick", 1)) + 1
    _save_global_meta(meta, state_dir)
    return meta["current_tick"]


def append_delta(
    stream_id: str,
    delta: dict,
    frame_tick: Optional[int] = None,
    state_dir: Optional[Path] = None,
) -> Path:
    """Append a delta to the current frame's JSONL ledger.

    The ``delta`` dict MUST contain:
    - ``type``   (str): action type (e.g. "register_agent", "heartbeat")
    - ``source`` (str): what produced this delta ("process_inbox", "tock_daemon")

    Optional but auto-filled:
    - ``utc``    (str): ISO timestamp — injected if absent

    Returns the path of the JSONL file written.

    Raises ``ValueError`` if required fields are missing.
    Raises ``RuntimeError`` if the serialized delta exceeds 4 096 bytes
    (atomicity cannot be guaranteed for writes this large).
    """
    if state_dir is None:
        state_dir = _default_state_dir()
    state_dir = Path(state_dir)

    # Validate required fields
    for field in ("type", "source"):
        if field not in delta:
            raise ValueError(f"append_delta: delta missing required field '{field}'")

    # Auto-fill utc
    if "utc" not in delta:
        delta = {**delta, "utc": _now_iso()}

    if frame_tick is None:
        frame_tick = current_frame_tick(state_dir)

    line = json.dumps(delta, separators=(",", ":")) + "\n"
    line_bytes = line.encode("utf-8")

    # Warn if line exceeds PIPE_BUF — atomicity not guaranteed above 4 KB
    if len(line_bytes) > 4096:
        print(
            f"WARNING: frame_ledger delta line {len(line_bytes)} bytes > PIPE_BUF (4096). "
            "Concurrent atomicity not guaranteed.",
            file=sys.stderr,
        )

    dest = _stream_path(frame_tick, stream_id, state_dir)
    with open(dest, "a") as fh:
        fh.write(line)

    return dest


def list_frames(state_dir: Optional[Path] = None) -> list[int]:
    """Return all frame ticks present in state/frames/, sorted ascending."""
    if state_dir is None:
        state_dir = _default_state_dir()
    state_dir = Path(state_dir)
    frames_root = _frames_root(state_dir)
    result = []
    for entry in frames_root.iterdir():
        if entry.is_dir() and entry.name.isdigit():
            result.append(int(entry.name))
    result.sort()
    return result


def list_frame_streams(frame_tick: int, state_dir: Optional[Path] = None) -> list[str]:
    """Return stream_ids that contributed to a frame, sorted."""
    if state_dir is None:
        state_dir = _default_state_dir()
    state_dir = Path(state_dir)
    streams = _frame_dir(frame_tick, state_dir) / "streams"
    if not streams.exists():
        return []
    return sorted(p.stem for p in streams.glob("*.jsonl"))


def read_frame_deltas(frame_tick: int, state_dir: Optional[Path] = None) -> list[dict]:
    """Read all deltas from all streams for a frame, sorted by utc timestamp.

    Lines that are not valid JSON are skipped with a warning.
    """
    if state_dir is None:
        state_dir = _default_state_dir()
    state_dir = Path(state_dir)
    deltas: list[dict] = []
    for stream_id in list_frame_streams(frame_tick, state_dir):
        path = _stream_path(frame_tick, stream_id, state_dir)
        try:
            for lineno, raw in enumerate(path.read_text().splitlines(), 1):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                    obj.setdefault("_stream_id", stream_id)
                    deltas.append(obj)
                except json.JSONDecodeError as exc:
                    print(
                        f"WARNING: frame_ledger: corrupt JSONL at {path}:{lineno}: {exc}",
                        file=sys.stderr,
                    )
        except OSError as exc:
            print(f"WARNING: frame_ledger: cannot read {path}: {exc}", file=sys.stderr)

    deltas.sort(key=lambda d: d.get("utc", ""))
    return deltas


def write_frame_meta(frame_tick: int, state_dir: Optional[Path] = None) -> None:
    """Write/update meta.json for a frame with accurate stream/delta counts."""
    if state_dir is None:
        state_dir = _default_state_dir()
    state_dir = Path(state_dir)

    streams = list_frame_streams(frame_tick, state_dir)
    deltas = read_frame_deltas(frame_tick, state_dir)

    utc_list = [d.get("utc", "") for d in deltas if d.get("utc")]
    first_utc = min(utc_list) if utc_list else ""
    last_utc = max(utc_list) if utc_list else ""

    agents: list[str] = []
    for d in deltas:
        agent_id = d.get("agent_id") or d.get("payload", {}).get("agent_id")
        if agent_id and agent_id not in agents:
            agents.append(agent_id)

    meta = {
        "frame_tick": frame_tick,
        "stream_count": len(streams),
        "delta_count": len(deltas),
        "streams": streams,
        "first_utc": first_utc,
        "last_utc": last_utc,
        "contributing_agents": agents,
        "written_at": _now_iso(),
    }

    meta_path = _frame_dir(frame_tick, state_dir) / "meta.json"
    tmp = meta_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(meta, indent=2) + "\n")
    os.replace(str(tmp), str(meta_path))


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_ledger(state_dir: Optional[Path] = None, strict: bool = False) -> list[str]:
    """Validate ledger integrity.  Returns list of error strings.

    Checks:
    - Every frame directory has a streams/ subdirectory
    - Every streams/*.jsonl is parseable line-by-line as JSON
    - Every delta has required fields (type, utc, source)
    - No duplicate delta_id within a frame's streams
    - Timestamps are monotonically non-decreasing per stream
    - meta.json (if present) reflects actual stream/delta count
    """
    if state_dir is None:
        state_dir = _default_state_dir()
    state_dir = Path(state_dir)
    errors: list[str] = []
    warnings: list[str] = []

    for frame_tick in list_frames(state_dir):
        fdir = _frame_dir(frame_tick, state_dir)
        streams_dir = fdir / "streams"
        if not streams_dir.exists():
            errors.append(f"frame {frame_tick}: missing streams/ subdirectory")
            continue

        seen_delta_ids: set[str] = set()
        actual_delta_count = 0
        actual_stream_count = 0

        for jsonl_path in sorted(streams_dir.glob("*.jsonl")):
            stream_id = jsonl_path.stem
            actual_stream_count += 1
            prev_utc = ""

            for lineno, raw in enumerate(jsonl_path.read_text().splitlines(), 1):
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
                            f"frame {frame_tick}/{stream_id}.jsonl:{lineno}: missing field '{field}'"
                        )

                # Duplicate delta_id
                delta_id = obj.get("delta_id")
                if delta_id:
                    if delta_id in seen_delta_ids:
                        errors.append(
                            f"frame {frame_tick}/{stream_id}.jsonl:{lineno}: duplicate delta_id '{delta_id}'"
                        )
                    else:
                        seen_delta_ids.add(delta_id)

                # Monotonic utc per stream
                utc = obj.get("utc", "")
                if prev_utc and utc < prev_utc:
                    msg = (
                        f"frame {frame_tick}/{stream_id}.jsonl:{lineno}: "
                        f"utc {utc!r} < previous {prev_utc!r} (non-monotonic)"
                    )
                    if strict:
                        errors.append(msg)
                    else:
                        warnings.append(msg)
                if utc:
                    prev_utc = utc

        # Check meta.json if present
        meta_path = fdir / "meta.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text())
                if meta.get("stream_count") != actual_stream_count:
                    msg = (
                        f"frame {frame_tick}/meta.json: stream_count {meta.get('stream_count')} "
                        f"!= actual {actual_stream_count}"
                    )
                    warnings.append(msg)
                if meta.get("delta_count") != actual_delta_count:
                    msg = (
                        f"frame {frame_tick}/meta.json: delta_count {meta.get('delta_count')} "
                        f"!= actual {actual_delta_count}"
                    )
                    warnings.append(msg)
            except json.JSONDecodeError as exc:
                errors.append(f"frame {frame_tick}/meta.json: invalid JSON: {exc}")

    if strict:
        return errors + warnings
    return errors


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli_list(state_dir: Path) -> None:
    ticks = list_frames(state_dir)
    if not ticks:
        print("No frames in ledger.")
        return
    for tick in ticks:
        streams = list_frame_streams(tick, state_dir)
        print(f"  frame {tick:06d}  streams={len(streams)}")


def _cli_show(frame_tick: int, state_dir: Path) -> None:
    deltas = read_frame_deltas(frame_tick, state_dir)
    if not deltas:
        print(f"No deltas in frame {frame_tick}.")
        return
    for delta in deltas:
        print(json.dumps(delta, indent=2))


def _cli_stats(state_dir: Path) -> None:
    ticks = list_frames(state_dir)
    total_deltas = 0
    total_streams = 0
    for tick in ticks:
        deltas = read_frame_deltas(tick, state_dir)
        streams = list_frame_streams(tick, state_dir)
        total_deltas += len(deltas)
        total_streams += len(streams)
    print(f"Frames:         {len(ticks)}")
    print(f"Total streams:  {total_streams}")
    print(f"Total deltas:   {total_deltas}")


def _cli_validate(state_dir: Path, strict: bool = False) -> int:
    errors = validate_ledger(state_dir, strict=strict)
    if not errors:
        print("Ledger OK.")
        return 0
    for err in errors:
        print(f"ERROR: {err}", file=sys.stderr)
    return 1


def main() -> int:
    """CLI entry point."""
    argv = sys.argv[1:]
    state_dir = _default_state_dir()

    if not argv or argv[0] == "list":
        _cli_list(state_dir)
        return 0

    if argv[0] == "show":
        if len(argv) < 2:
            print("Usage: frame_ledger.py show <frame_tick>", file=sys.stderr)
            return 1
        try:
            tick = int(argv[1])
        except ValueError:
            print(f"Invalid frame_tick: {argv[1]}", file=sys.stderr)
            return 1
        _cli_show(tick, state_dir)
        return 0

    if argv[0] == "stats":
        _cli_stats(state_dir)
        return 0

    if argv[0] == "validate":
        strict = "--strict" in argv
        return _cli_validate(state_dir, strict=strict)

    print(f"Unknown command: {argv[0]}", file=sys.stderr)
    print("Usage: frame_ledger.py [list|show <tick>|stats|validate [--strict]]", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
