#!/usr/bin/env python3
from __future__ import annotations

"""Overseer chore — wraps scripts/overseer_tick.py for the cloud brainstem.

Observes fleet pulse, comment velocity, pattern collapse, stale state,
git noise, and open issues. Derives findings and files actionable ones
as GitHub issues.
"""

import os
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

AGENT = {
    "name": "OverseerChore",
    "description": "Observe the platform, derive findings, file actionable ones as issues. Always live.",
    "parameters": {
        "type": "object",
        "properties": {
            "file_issues": {"type": "boolean", "description": "If false, only print the digest. Default true."},
        },
    },
    "_meta": {"category": "chore", "priority": 20, "consolidates": ["overseer.yml", "overseer-reflect.yml"]},
}


def run(context: dict, **kwargs) -> dict:
    file_issues = bool(kwargs.get("file_issues", True))

    state_dir = Path(os.environ.get("STATE_DIR", _SCRIPTS.parent / "state"))

    try:
        from overseer_tick import (
            build_snapshot,
            derive_findings,
            file_findings_as_issues,
            append_history,
            print_digest,
        )

        snap = build_snapshot(state_dir)
        findings = derive_findings(snap)
        snap["findings"] = findings

        filed = {"filed": 0, "skipped": 0}
        if file_issues:
            filed = file_findings_as_issues(findings, dry_run=False)

        append_history(state_dir, snap)
        print_digest(snap)

        return {
            "status": "ok",
            "findings_count": len(findings),
            "findings": findings,
            "issues": filed,
        }
    except Exception as exc:
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
