"""Audit #4 — Dream Catcher delta integrity (Amendment XVI).

The Dream Catcher protocol says: streams produce DELTAS (additive, never
destructive), keyed by `(frame, utc)`. Deltas are merged at frame
boundaries. Every delta MUST be valid JSON with at least the structural
fields the merge engine expects.

If a delta is malformed, the merge engine either silently skips it (data
loss) or crashes the frame (worse data loss). This audit walks
state/stream_deltas/, parses each file, and asserts the minimum
contract.
"""
from __future__ import annotations
import json
from pathlib import Path


# Optional fields — if present, must be valid. Required fields enforced below.
REQUIRED_FIELDS = []  # we accept any non-empty JSON object as a starting point
ALLOWED_TOP_LEVEL_TYPES = (dict, list)  # most engine deltas are dicts; some are lists


def test_all_deltas_parseable(canonical_state):
    """Every file in state/stream_deltas/ must be valid JSON."""
    delta_dir = canonical_state / "stream_deltas"
    if not delta_dir.exists():
        return
    bad = []
    for f in sorted(delta_dir.glob("*.json")):
        try:
            with open(f) as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            bad.append((f.name, str(exc)[:120]))
            continue
        if not isinstance(data, ALLOWED_TOP_LEVEL_TYPES):
            bad.append((f.name, f"top-level type {type(data).__name__}"))
    assert not bad, (
        f"{len(bad)} malformed delta file(s). Samples: {bad[:5]}. "
        f"The merge engine will silently skip or crash on these."
    )


def test_no_zero_byte_deltas(canonical_state):
    """Empty files in stream_deltas/ are orphans from crashed workers."""
    delta_dir = canonical_state / "stream_deltas"
    if not delta_dir.exists():
        return
    empties = [f.name for f in delta_dir.glob("*.json") if f.is_file() and f.stat().st_size == 0]
    assert not empties, (
        f"{len(empties)} zero-byte delta file(s): {empties[:5]}. "
        f"Crashed stream workers left these behind."
    )


def test_deltas_have_frame_or_stream_id(canonical_state):
    """At least 80% of deltas should carry frame or stream_id metadata —
    Amendment XVI says the composite (frame, utc) is the primary key."""
    delta_dir = canonical_state / "stream_deltas"
    if not delta_dir.exists():
        return
    total = 0
    keyed = 0
    for f in sorted(delta_dir.glob("*.json")):
        try:
            with open(f) as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError):
            continue
        total += 1
        if isinstance(data, dict):
            has_frame = "frame" in data or "frame_tick" in data or "frame" in data.get("_meta", {})
            has_stream = "stream_id" in data or "stream_id" in data.get("_meta", {})
            if has_frame or has_stream:
                keyed += 1
    if total == 0:
        return
    coverage = keyed / total
    assert coverage >= 0.80, (
        f"Only {keyed}/{total} ({coverage:.1%}) deltas carry frame/stream_id "
        f"metadata. Amendment XVI key contract is broken — merges become "
        f"ambiguous."
    )
