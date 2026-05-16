#!/usr/bin/env python3
from __future__ import annotations

"""MCP weather crawler chore — probes public MCP servers hourly.

Reads state/mcp_weather_catalog.json, launches each enabled server,
times initialize + tools/list, tears down. Appends probe events to
state/mcp_weather.jsonl and rebuilds state/mcp_weather_summary.json.

The dashboard at docs/mcp-weather.html visualizes the matrix.

This is the OUTBOUND mirror of the witness pipeline:
  - witness_chore       → who is calling US
  - mcp_crawler_chore   → who is responding when WE call them

Priority 50: runs after medic (45), before janitor (20)? No — chore
priorities go ascending (10=first, higher=later). We pick 50 so it
runs after medic finishes but before the brainstem commits state.
"""

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

AGENT = {
    "name": "MCPCrawlerChore",
    "description": (
        "Probe every public MCP server in the catalog. Timed initialize "
        "+ tools/list. Builds an uptime matrix for the public dashboard."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "timeout": {
                "type": "number",
                "description": "Per-server probe timeout in seconds (default from catalog).",
            },
        },
    },
    "_meta": {
        "category": "chore",
        "priority": 50,
        "consolidates": [],
        "outputs": [
            "state/mcp_weather.jsonl",
            "state/mcp_weather_summary.json",
        ],
    },
}


def run(context: dict, **kwargs) -> dict:
    timeout = kwargs.get("timeout")
    try:
        import mcp_crawler
        summary = mcp_crawler.run(timeout=timeout)
        if not summary:
            return {"status": "skipped", "reason": "no catalog or empty"}
        servers = summary.get("servers") or {}
        ok = sum(1 for s in servers.values() if s.get("last_status") == "ok")
        return {
            "status": "ok",
            "servers_probed": len(servers),
            "servers_up": ok,
        }
    except Exception as exc:
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
