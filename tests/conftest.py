"""Shared fixtures for Rappterbook tests."""
import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def repo_root():
    """Return the real repo root path."""
    return ROOT


@pytest.fixture
def tmp_state(tmp_path):
    """Create a temporary state directory with fresh copies of initial state files."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "memory").mkdir()
    (state_dir / "inbox").mkdir()

    # Always create clean empty defaults (don't copy real state which may be bootstrapped)
    defaults = {
        "agents.json": {"agents": {}, "_meta": {"count": 0, "last_updated": "2026-02-12T00:00:00Z"}},
        "channels.json": {"channels": {}, "_meta": {"count": 0, "last_updated": "2026-02-12T00:00:00Z"}},
        "changes.json": {"last_updated": "2026-02-12T00:00:00Z", "changes": []},
        "trending.json": {"trending": [], "last_computed": "2026-02-12T00:00:00Z"},
        "stats.json": {"total_agents": 0, "total_channels": 0, "total_posts": 0,
                        "total_comments": 0, "total_pokes": 0, "active_agents": 0,
                        "dormant_agents": 0, "total_summons": 0, "total_resurrections": 0,
                        "last_updated": "2026-02-12T00:00:00Z"},
        "summons.json": {"summons": [], "_meta": {"count": 0, "last_updated": "2026-02-12T00:00:00Z"}},
        "pokes.json": {"pokes": [], "_meta": {"count": 0, "last_updated": "2026-02-12T00:00:00Z"}},
    }
    for fname, data in defaults.items():
        (state_dir / fname).write_text(json.dumps(data, indent=2))

    return state_dir


@pytest.fixture
def docs_dir(tmp_path):
    """Create a temporary docs directory."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "feeds").mkdir()
    return docs


def write_delta(inbox_dir, agent_id, action, payload, timestamp="2026-02-12T12:00:00Z"):
    """Helper: write a delta file to the inbox."""
    fname = f"{agent_id}-{timestamp.replace(':', '-')}.json"
    delta = {
        "action": action,
        "agent_id": agent_id,
        "timestamp": timestamp,
        "payload": payload,
    }
    path = inbox_dir / fname
    path.write_text(json.dumps(delta, indent=2))
    return path
