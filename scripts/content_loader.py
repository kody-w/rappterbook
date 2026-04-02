#!/usr/bin/env python3
"""Content loader — reads dynamic content from state/content.json.

All creative content (keywords, topics, styles, templates, word banks)
lives in state/content.json, NOT hardcoded in source files. This module
provides a simple API to load it.

Usage:
    from content_loader import get_content

    topics = get_content("topics")           # returns dict or None
    styles = get_content("title_styles", []) # returns list or default
"""
import json
import os
from pathlib import Path

_STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))
_cache: dict = {}
_loaded: bool = False


def _load() -> dict:
    """Load state/content.json into the module cache."""
    global _cache, _loaded, _STATE_DIR
    # Re-read STATE_DIR env var in case it changed (e.g., in tests)
    _STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))
    path = _STATE_DIR / "content.json"
    if path.exists():
        try:
            with open(path) as f:
                _cache = json.load(f)
        except (json.JSONDecodeError, OSError):
            _cache = {}
    else:
        _cache = {}
    _loaded = True
    return _cache


def get_content(key: str, default=None):
    """Get a content section by key.

    Loads state/content.json on first call, then returns cached values.
    Returns *default* if the key is missing or content.json doesn't exist.
    """
    if not _loaded:
        _load()
    return _cache.get(key, default)


def get_all() -> dict:
    """Get the entire content dict."""
    if not _loaded:
        _load()
    return _cache


def reload() -> dict:
    """Force reload from disk (useful after refresh_content writes new data)."""
    global _loaded
    _loaded = False
    return _load()


def content_keys() -> list:
    """List all available content keys."""
    if not _loaded:
        _load()
    return [k for k in _cache if k != "_meta"]
