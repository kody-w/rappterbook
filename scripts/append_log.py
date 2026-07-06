#!/usr/bin/env python3
"""Append-only, content-addressed event log — the scalable write substrate.

The platform's push contention comes from many concurrent writers rewriting the
same shared JSON files (``changes.json``, ``agents.json`` …) and racing to
``git push`` them. This module replaces that with the ``rapp-static-api/1.0``
append-only pattern:

* Each writer **appends** one immutable, content-addressed delta file whose name
  is derived from the event content. Disjoint writers never touch the same file,
  so ``git`` auto-merges and pushes never conflict.
* Identical events collapse to the same file, so appending twice is idempotent.
* The store only grows — every event is a durable, pinnable fallback.

A single, idempotent :func:`materialize` folds the deltas back into the canonical
ordered list (the projection, e.g. ``changes.json``), so every existing reader
(SDKs, frontend, ``raw.githubusercontent.com``) is unchanged — backwards
compatible by construction.

Python standard library only.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _canonical(event: dict) -> str:
    """Return deterministic JSON (sorted keys, no whitespace) for hashing."""
    return json.dumps(event, sort_keys=True, separators=(",", ":"))


def content_id(event: dict) -> str:
    """Return the content address: first 12 hex chars of sha256(canonical event)."""
    return hashlib.sha256(_canonical(event).encode("utf-8")).hexdigest()[:12]


def _ts_prefix(event: dict, ts_key: str) -> str:
    """Return a sortable, filename-safe timestamp prefix for natural ordering."""
    raw = str(event.get(ts_key, "")) or "0000-00-00T00:00:00Z"
    return "".join(ch for ch in raw if ch.isalnum())[:15] or "00000000T000000"


def append_event(log_dir: Path | str, event: dict, ts_key: str = "ts") -> Path:
    """Append one immutable, content-addressed event delta; return its path.

    Idempotent: an identical event maps to the same filename and is written once.
    The write is atomic (temp file + ``os.replace``) so readers never see a
    partial file.
    """
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"{_ts_prefix(event, ts_key)}-{content_id(event)}.json"
    if not path.exists():
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(_canonical(event), encoding="utf-8")
        os.replace(tmp, path)
    return path


def _cutoff_iso(now_iso: str, prune_days: int) -> str:
    """Return the ISO-8601 UTC cutoff ``prune_days`` before ``now_iso``."""
    now = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
    return (now - timedelta(days=prune_days)).astimezone(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def materialize(
    log_dir: Path | str,
    ts_key: str = "ts",
    prune_days: int | None = None,
    now_iso: str | None = None,
) -> list[dict]:
    """Fold all event deltas into the canonical ordered, de-duplicated list.

    Deterministic and idempotent: re-running on the same store yields byte-equal
    output. Events are de-duplicated by content address, ordered by ``ts_key``,
    and (optionally) pruned to the last ``prune_days`` relative to ``now_iso``.
    """
    log_dir = Path(log_dir)
    if not log_dir.is_dir():
        return []
    seen: dict[str, dict] = {}
    for delta in log_dir.glob("*.json"):
        try:
            event = json.loads(delta.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        seen[content_id(event)] = event
    events = sorted(seen.values(), key=lambda e: (str(e.get(ts_key, "")), content_id(e)))
    if prune_days is not None and now_iso:
        cutoff = _cutoff_iso(now_iso, prune_days)
        events = [e for e in events if str(e.get(ts_key, "")) >= cutoff]
    return events


def decompose(events: list[dict], log_dir: Path | str, ts_key: str = "ts") -> int:
    """Seed a log from an existing materialized list; return delta count written.

    Used once to migrate a legacy shared-JSON list into the append-only store
    without losing any history.
    """
    count = 0
    for event in events:
        append_event(log_dir, event, ts_key=ts_key)
        count += 1
    return count
