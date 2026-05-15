#!/usr/bin/env python3
from __future__ import annotations

"""Janitor chore — wraps scripts/janitor_tick.py for the cloud brainstem.

Sweeps zombie locks and auto-closes stale issues. The underlying script
exposes only main(); we call its internals directly so we can return
structured results to the brainstem.
"""

import os
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

AGENT = {
    "name": "JanitorChore",
    "description": "Sweep zombie locks and auto-close stale GitHub issues. Always live.",
    "parameters": {
        "type": "object",
        "properties": {
            "max_lock_age_hours": {"type": "integer", "description": "Default 2."},
            "max_issue_age_days": {"type": "integer", "description": "Default 7."},
            "issue_limit": {"type": "integer", "description": "Max issues to close per tick. Default 25."},
        },
    },
    "_meta": {"category": "chore", "priority": 10, "consolidates": ["janitor.yml"]},
}


def run(context: dict, **kwargs) -> dict:
    max_lock_age = int(kwargs.get("max_lock_age_hours", 2))
    max_issue_age = int(kwargs.get("max_issue_age_days", 7))
    issue_limit = int(kwargs.get("issue_limit", 25))

    state_dir = Path(os.environ.get("STATE_DIR", _SCRIPTS.parent / "state"))

    try:
        from janitor_tick import sweep_zombie_locks, close_stale_issues, append_log
        from state_io import now_iso

        lock_result = sweep_zombie_locks(state_dir, max_lock_age, False)
        issue_result = close_stale_issues(max_issue_age, issue_limit, False)

        entry = {
            "timestamp": now_iso(),
            "locks": lock_result,
            "issues": issue_result,
        }
        append_log(state_dir, entry)
        return {"status": "ok", **entry}
    except Exception as exc:
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
