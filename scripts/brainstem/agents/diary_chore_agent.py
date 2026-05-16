#!/usr/bin/env python3
from __future__ import annotations

"""Diary chore — Marginalia writes one entry per UTC day.

The brainstem ticks hourly. This chore is date-guarded: it writes the
day's entry exactly once. Re-running after the entry exists is a no-op.

Priority 70 — runs after the firehose aggregator (60) so Marginalia
has fresh material to reflect on.

The entry is the canonical first-person record of the day. Over five
years that becomes 1,825 entries — the longest continuous AI
autobiography ever written.
"""

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

AGENT = {
    "name": "DiaryChore",
    "description": (
        "Marginalia writes today's diary entry (one per UTC day). "
        "First-person, ~280 words, archived to docs/diary/. "
        "Frozen voice; the same daemon writes every entry forever."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "force": {
                "type": "boolean",
                "description": "Re-generate even if today's entry already exists.",
            },
        },
    },
    "_meta": {
        "category": "chore",
        "priority": 70,
        "consolidates": [],
        "outputs": [
            "docs/diary/{YYYY-MM-DD}.md",
            "state/diary_state.json",
            "state/diary_index.json",
        ],
    },
}


def run(context: dict, **kwargs) -> dict:
    try:
        import diary_entry
        report = diary_entry.run(force=bool(kwargs.get("force", False)))
        return {"status": "ok", **report}
    except Exception as exc:
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
