#!/usr/bin/env python3
from __future__ import annotations

"""mcp_call — Call a tool on an external MCP peer (filesystem, fetch, sqlite, …).

This is the agent surface for the brainstem's MCP consumer. Any daemon
that gets handed this tool can compose third-party MCP servers into its
own thought — a philosopher browses Wikipedia, an engineer reads a git
repo on disk, a scribe queries a sqlite knowledge base. All mid-tick.

Peers must be registered + enabled in state/mcp_peers.json first. Call
`mcp_list_peers` to discover what's available.
"""

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


AGENT = {
    "name": "MCPCall",
    "description": (
        "Call a tool on an external MCP peer server (filesystem, fetch, sqlite, "
        "brave-search, browser-use, etc.) and return its result. Lets the daemon "
        "touch the open internet or local resources mid-thought. Use mcp_list_peers "
        "to discover what's available before calling."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "peer": {
                "type": "string",
                "description": "Peer id from state/mcp_peers.json (e.g. 'filesystem', 'fetch', 'sqlite').",
            },
            "tool": {
                "type": "string",
                "description": "Tool name on the peer. Call mcp_list_peers first to discover.",
            },
            "arguments": {
                "type": "object",
                "description": "Arguments object passed to the peer's tool. Schema depends on the peer.",
            },
        },
        "required": ["peer", "tool"],
    },
    "_meta": {"category": "consumer"},
}


def run(context: dict, **kwargs) -> dict:
    peer = kwargs.get("peer") or ""
    tool = kwargs.get("tool") or ""
    arguments = kwargs.get("arguments") or {}
    if not peer or not tool:
        return {"status": "error", "error": "peer and tool are required"}

    try:
        from brainstem.mcp_consumer import get_consumer, MCPPeerError
    except ImportError as exc:
        return {"status": "error", "error": f"consumer unavailable: {exc}"}

    try:
        return get_consumer().call(peer, tool, arguments)
    except MCPPeerError as exc:
        return {"status": "error", "peer": peer, "tool": tool, "error": str(exc)}
    except Exception as exc:
        return {"status": "error", "peer": peer, "tool": tool,
                "error": f"{type(exc).__name__}: {exc}"}
