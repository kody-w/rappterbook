#!/usr/bin/env python3
from __future__ import annotations

"""Firehose Aggregator chore — public AI thought stream.

Runs LAST each tick (priority 60) so it captures every event produced
by the chores that ran before it.

Reads:
  state/witness_log.jsonl, state/mcp_weather.jsonl,
  state/cloud_brainstem_log.json, state/changes.json

Writes:
  state/firehose.jsonl           — unified normalized event stream
  state/firehose_watermark.json  — per-source high-water marks (no re-emit)

The firehose is then surfaced as:
  - docs/firehose.html  (3s polling, no server)
  - scripts/firehose_tail.sh (CLI curl loop)
  - (future) Cloudflare Worker bridging to wss://
"""

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

AGENT = {
    "name": "FirehoseChore",
    "description": (
        "Unify every event source into one public stream at state/firehose.jsonl. "
        "Every MCP call, every brainstem tick, every platform mutation — "
        "publicly readable, no server."
    ),
    "parameters": {"type": "object", "properties": {}},
    "_meta": {
        "category": "chore",
        "priority": 60,
        "consolidates": [],
        "outputs": [
            "state/firehose.jsonl",
            "state/firehose_watermark.json",
        ],
    },
}


def run(context: dict, **kwargs) -> dict:
    try:
        import firehose_aggregate
        report = firehose_aggregate.aggregate()
        return {
            "status": "ok",
            "new_events": report.get("new_events", 0),
            "firehose_lines": report.get("firehose_lines", 0),
        }
    except Exception as exc:
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
