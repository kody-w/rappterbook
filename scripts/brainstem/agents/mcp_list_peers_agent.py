#!/usr/bin/env python3
from __future__ import annotations

"""mcp_list_peers — Discover external MCP peers and the tools they expose.

Returns the snapshot a daemon (or external LLM) needs to plan an
mcp_call. For each registered peer: description, enabled state, and —
when enabled — the full list of tools the peer's MCP server reports.
"""

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


AGENT = {
    "name": "MCPListPeers",
    "description": (
        "List every external MCP peer registered in state/mcp_peers.json. "
        "For enabled peers, also returns the tool catalog the peer exposes "
        "(name + short description). Call this before mcp_call."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "only_enabled": {
                "type": "boolean",
                "description": "If true, skip disabled peers in the response. Default false.",
            },
        },
    },
    "_meta": {"category": "consumer"},
}


def run(context: dict, **kwargs) -> dict:
    only_enabled = bool(kwargs.get("only_enabled", False))
    try:
        from brainstem.mcp_consumer import get_consumer
    except ImportError as exc:
        return {"status": "error", "error": f"consumer unavailable: {exc}"}

    snapshot = get_consumer().describe_all()
    if only_enabled:
        snapshot = {pid: entry for pid, entry in snapshot.items() if entry.get("enabled")}
    return {
        "status": "ok",
        "peer_count": len(snapshot),
        "peers": snapshot,
    }
