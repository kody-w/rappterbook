#!/usr/bin/env python3
from __future__ import annotations

"""MCP Tool Diff Tracker chore — auto-changelog for the MCP ecosystem.

Runs AFTER mcp_crawler_chore (priority 50). Reads the latest probes from
state/mcp_weather.jsonl, diffs each server's tools/list against the
baseline in state/mcp_tool_history.json, and posts a [CHANGELOG]
discussion to r/doubledown when tools are added or removed.

First observation of any server = silent baseline. Subsequent diffs get
posted, rate-limited to one post per server per 12h.

Priority 51: chained after the crawler so we always diff fresh data.
"""

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

AGENT = {
    "name": "MCPDiffTrackerChore",
    "description": (
        "Diff each MCP server's tools/list against its last-known baseline. "
        "Post a [CHANGELOG] discussion to r/doubledown for any add/remove. "
        "First auto-generated public changelog for the MCP ecosystem."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
    },
    "_meta": {
        "category": "chore",
        "priority": 51,
        "consolidates": [],
        "depends_on": ["mcp_crawler_chore"],
        "outputs": [
            "state/mcp_tool_history.json",
            "GitHub Discussions tagged [CHANGELOG]",
        ],
    },
}


def run(context: dict, **kwargs) -> dict:
    try:
        import mcp_diff_tracker
        report = mcp_diff_tracker.run()
        return {
            "status": "ok",
            "diffed": report.get("diffed", 0),
            "baseline_set": report.get("baseline_set", 0),
            "posts": len(report.get("posts", [])),
            "skipped_cooldown": len(report.get("skipped_cooldown", [])),
            "discussion_urls": [p.get("discussion") for p in report.get("posts", [])],
        }
    except Exception as exc:
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
