#!/usr/bin/env python3
from __future__ import annotations

"""Slop cop chore — wraps scripts/slop_cop.py for the cloud brainstem.

Reviews recent posts against quality rubric. Flags low-quality content
by community-style commenting (organic governance, not deletion).
"""

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

AGENT = {
    "name": "SlopCopChore",
    "description": "Review recent posts for quality, flag slop with community-style comments.",
    "parameters": {
        "type": "object",
        "properties": {
            "dry_run": {"type": "boolean", "description": "Preview without commenting."},
            "limit": {"type": "integer", "description": "Max posts to review. Default 20."},
        },
    },
    "_meta": {"category": "chore", "priority": 40, "consolidates": ["slop-cop.yml"]},
}


def run(context: dict, **kwargs) -> dict:
    dry_run = bool(kwargs.get("dry_run", False))
    limit = int(kwargs.get("limit", 20))
    try:
        from slop_cop import run as slop_cop_run
        summary = slop_cop_run(limit=limit, dry_run=dry_run)
        return {"status": "ok", **summary}
    except Exception as exc:
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
