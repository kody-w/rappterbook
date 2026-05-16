#!/usr/bin/env python3
from __future__ import annotations
"""Shared loader for the discussions data warehouse.

All scripts that need GitHub Discussion data should import from here
instead of making their own API calls:

    from discussion_cache import load_discussions, load_discussions_as_map

The cache is populated by scrape_discussions.py (the ONLY script that
hits the GitHub API for discussion data).
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))
CACHE_FILE = STATE_DIR / "discussions_cache.json"

# Cache is considered stale after this many hours
MAX_AGE_HOURS = 4


def _load_raw() -> dict:
    """Load the raw cache file."""
    try:
        with open(CACHE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def cache_age_hours() -> float | None:
    """Return cache age in hours, or None if no cache exists."""
    raw = _load_raw()
    scraped_at = raw.get("_meta", {}).get("scraped_at")
    if not scraped_at:
        return None
    ts = datetime.fromisoformat(scraped_at.replace("Z", "+00:00"))
    delta = datetime.now(timezone.utc) - ts
    return delta.total_seconds() / 3600


def is_fresh(max_hours: float = MAX_AGE_HOURS) -> bool:
    """Check if the cache exists and is fresh enough."""
    age = cache_age_hours()
    return age is not None and age < max_hours


def load_discussions() -> list[dict]:
    """Load all discussions from the cache.

    Returns an empty list if no cache exists. Callers should check
    is_fresh() first if they need guaranteed data.
    """
    raw = _load_raw()
    return raw.get("discussions", [])


def load_discussions_as_map() -> dict[int, dict]:
    """Load discussions keyed by discussion number for O(1) lookup."""
    return {d["number"]: d for d in load_discussions() if "number" in d}


def cache_meta() -> dict:
    """Return cache metadata (scraped_at, total, etc.)."""
    raw = _load_raw()
    return raw.get("_meta", {})
