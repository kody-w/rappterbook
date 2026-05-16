#!/usr/bin/env python3
from __future__ import annotations

"""Witness chore — digest state/witness_log.jsonl → state/witness_summary.json.

Runs once per brainstem tick. Keeps the public dashboard fresh without
needing a separate workflow. Cheap (one file scan, all in-memory).
"""

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

AGENT = {
    "name": "WitnessChore",
    "description": "Compress the MCP witness log into a summary the dashboard can fetch.",
    "parameters": {"type": "object", "properties": {}},
    "_meta": {"category": "chore", "priority": 35, "consolidates": []},
}


def run(context: dict, **kwargs) -> dict:
    try:
        from witness_digest import digest
        from state_io import save_json
        import os

        state_dir = Path(os.environ.get("STATE_DIR", _SCRIPTS.parent / "state"))
        summary = digest()
        save_json(state_dir / "witness_summary.json", summary)
        return {
            "status": "ok",
            "rows_scanned": summary["_meta"]["rows_scanned"],
            "totals_lifetime": summary["totals_lifetime"],
            "funnel": summary["funnel"],
        }
    except Exception as exc:
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
