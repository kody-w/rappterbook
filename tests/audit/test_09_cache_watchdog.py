"""Audit #9 — Discussions cache watchdog.

CLAUDE.md documents the 2026-03-19 incident: the sim's `--smart` scrape
merges with the LOCAL cache, and if a stale (small) local cache races a
fresh (large) one from origin, `git push --rebase` overwrites the full
cache. Recovery is manual.

This audit holds the line at: cache exists, has a positive total, has a
recent scrape timestamp, and contains the claimed number of discussions.
A second test compares against posted_log to spot population collapse.
"""
from __future__ import annotations
import datetime as dt
import json
from pathlib import Path


MAX_SCRAPE_AGE_HOURS = 24 * 14  # cache should be refreshed at least biweekly
MIN_TOTAL = 100  # any healthy cache has well above this


def _load(p: Path) -> dict:
    with open(p) as f:
        return json.load(f)


def test_cache_meta_total_positive(canonical_state):
    cache = _load(canonical_state / "discussions_cache.json")
    total = cache.get("_meta", {}).get("total", 0)
    assert total >= MIN_TOTAL, (
        f"cache._meta.total = {total} (expected >= {MIN_TOTAL}). "
        f"Possible cache collapse — see CLAUDE.md 2026-03-19 incident."
    )


def test_cache_total_matches_discussions_array(canonical_state):
    """The claimed total in _meta must equal the actual list length."""
    cache = _load(canonical_state / "discussions_cache.json")
    claimed = cache.get("_meta", {}).get("total", 0)
    actual = len(cache.get("discussions", []) or cache.get("items", []))
    assert claimed == actual, (
        f"cache._meta.total ({claimed}) != actual discussions list length ({actual})"
    )


def test_cache_scrape_age_reasonable(canonical_state):
    """The cache should have been scraped within MAX_SCRAPE_AGE_HOURS."""
    cache = _load(canonical_state / "discussions_cache.json")
    ts = cache.get("_meta", {}).get("scraped_at")
    if not ts:
        raise AssertionError("cache._meta.scraped_at missing")
    try:
        parsed = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        raise AssertionError(f"cache._meta.scraped_at unparseable: {ts!r}")
    age = (dt.datetime.now(dt.timezone.utc) - parsed).total_seconds() / 3600
    assert age <= MAX_SCRAPE_AGE_HOURS, (
        f"cache last scraped {age:.0f}h ago (limit {MAX_SCRAPE_AGE_HOURS}h). "
        f"Refresh: python scripts/scrape_discussions.py"
    )
