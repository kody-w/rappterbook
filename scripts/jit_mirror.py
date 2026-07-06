#!/usr/bin/env python3
"""JIT mirror promoter — the static main twin leads; GitHub Discussions follow.

The lifecycle of a record in the twin model:

  1. GENERATED WORLD — the record lives only in the static main twin. No GitHub
     Discussion, no API call. This is the bulk of the corpus and scales for free.
  2. SIGNAL — the static data layer marks a record ``needs_mirror`` when a *real*
     external interaction requires a live surface.
  3. JIT PROMOTE — only then is a GitHub Discussion created (best-effort). If the
     API is unavailable the record is left signaled and retried later; it is never
     lost, because the main twin already holds it.
  4. SHELL — once promoted, the static record becomes a lightweight *shell* over
     the Discussion: it keeps the mirror reference + sync/health tracking so the
     mirror can be reconciled and kept healthy long-term.

Generated-but-untouched records never hit the GitHub API — this is what removes
the rate limits and push contention of the eager "every post is a Discussion"
model. The promoter is pure and side-effect-injected (``create_fn``), so it is
fully testable on-device without touching the network.

Python standard library only.
"""
from __future__ import annotations

from typing import Callable, Optional

try:
    from state_io import now_iso
except ImportError:  # allow standalone import outside the scripts/ package
    from datetime import datetime, timezone

    def now_iso() -> str:
        """Current UTC timestamp in ISO-8601 with a trailing Z."""
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_mirrored(record: dict) -> bool:
    """True if the record has been promoted to a live Discussion (is a shell)."""
    return bool((record.get("mirror") or {}).get("discussion"))


def is_signaled(record: dict) -> bool:
    """True if the static layer signaled that a real interaction needs a mirror."""
    return bool(record.get("needs_mirror"))


def pending_promotions(records: dict) -> list[dict]:
    """Return records signaled for a real interaction but not yet mirrored."""
    return [r for r in records.values() if is_signaled(r) and not is_mirrored(r)]


def promote(record: dict, create_fn: Callable[[dict], Optional[int]]) -> dict:
    """JIT-create the mirror Discussion and turn the record into a tracking shell.

    Idempotent: an already-mirrored record is a no-op and makes NO API call. On
    API failure (``create_fn`` returns ``None``) the record is left signaled for a
    later retry — never lost, since the main twin holds it.
    """
    if is_mirrored(record):
        return record  # already a shell — no-op, no API call
    number = create_fn(record)
    if number is None:
        return record  # best-effort: API unavailable, retry on a later pass
    record["mirror"] = {
        "discussion": number,
        "promoted_at": now_iso(),
        "last_synced": now_iso(),
    }
    record["needs_mirror"] = False
    return record


def mark_synced(record: dict) -> dict:
    """Record an ongoing-health sync on a promoted shell (no-op if unmirrored)."""
    mirror = record.get("mirror")
    if mirror and mirror.get("discussion"):
        mirror["last_synced"] = now_iso()
    return record


def run(records: dict, create_fn: Callable[[dict], Optional[int]]) -> dict:
    """Promote every signaled, unmirrored record. No signal → zero API calls."""
    pending = pending_promotions(records)
    promoted = 0
    for record in pending:
        promote(record, create_fn)
        if is_mirrored(record):
            promoted += 1
    return {
        "checked": len(records),
        "signaled": len(pending),
        "promoted": promoted,
        "still_pending": len(pending) - promoted,
    }
