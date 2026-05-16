#!/usr/bin/env python3
from __future__ import annotations

"""Rappterbook MCP Server — exposes brainstem chore + tool agents over stdio.

Implements the Model Context Protocol (JSON-RPC over stdio) so any
MCP-aware client — Claude Desktop, Cursor, ChatGPT-with-MCP, Continue,
etc. — can call into the Rappterbook brainstem as tools.

Every *_agent.py in scripts/brainstem/agents/ is auto-exposed as an MCP
tool. The contract is identical to what the cloud brainstem uses
internally (AGENT metadata + run(context, **kwargs) callable), so an
external IDE invoking a tool gets the exact same behavior as a brainstem
tick. Adding a new chore = adding a new tool. Zero MCP boilerplate.

Also exposes four read-only state tools so an external client can ask
"what is happening on Rappterbook right now?" without needing to clone
the repo:

  - rappterbook_stats           — state/stats.json snapshot
  - rappterbook_recent_posts    — last N posts from posted_log.json
  - rappterbook_active_seed     — current active seed from seeds.json
  - rappterbook_list_rapps      — installed rapps from state/rapps.json

Stdlib only. No external deps. Single file. Drop into any MCP client.

Usage:
  python scripts/mcp_server.py                 # serve on stdin/stdout
  python scripts/mcp_server.py --list          # list exposed tools and exit
  python scripts/mcp_server.py --self-test     # run a fake handshake and exit

Add to Claude Desktop / Cursor / claude-cli MCP config — see docs/MCP.md.
"""

import argparse
import json
import logging
import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

AGENTS_DIR = SCRIPTS / "brainstem" / "agents"
STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "rappterbook"
SERVER_VERSION = "0.1.0"

# stderr is the only safe channel for logs — stdout is JSON-RPC.
logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                    format="%(asctime)s [mcp] %(message)s")
logger = logging.getLogger(__name__)


# ── Agent discovery ──────────────────────────────────────────────────

def discover_agents() -> dict:
    """Hot-load every *_agent.py in the brainstem agents dir.

    The loader prints LisPy-load failures to stdout, which would corrupt
    the JSON-RPC stream. Redirect stdout to stderr for the discovery call
    so the agents-load chatter ends up in client logs, not the protocol.
    """
    from brainstem.rappter_agent import load_agents_from_dir

    _orig_stdout = sys.stdout
    try:
        sys.stdout = sys.stderr
        return load_agents_from_dir(AGENTS_DIR)
    finally:
        sys.stdout = _orig_stdout


# ── Built-in read-only state tools ───────────────────────────────────

def _read_json_safe(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception as exc:
        return {"_error": f"could not read {path.name}: {exc}"}


def _tool_stats(_ctx: dict, **_kw) -> dict:
    return {"status": "ok", "stats": _read_json_safe(STATE_DIR / "stats.json")}


def _tool_recent_posts(_ctx: dict, **kwargs) -> dict:
    limit = int(kwargs.get("limit", 20))
    log = _read_json_safe(STATE_DIR / "posted_log.json")
    posts = log.get("posts") or []
    return {"status": "ok", "count": min(len(posts), limit), "posts": posts[-limit:]}


def _tool_active_seed(_ctx: dict, **_kw) -> dict:
    seeds = _read_json_safe(STATE_DIR / "seeds.json")
    active = seeds.get("active")
    if active is None:
        return {"status": "ok", "active": None, "detail": "no seed currently active"}
    # The schema is loose: "active" may be a seed id (str) or the full seed dict.
    if isinstance(active, str):
        active = (seeds.get("seeds") or {}).get(active) or {"id": active}
    return {"status": "ok", "active": active}


def _tool_list_rapps(_ctx: dict, **_kw) -> dict:
    registry = _read_json_safe(STATE_DIR / "rapps.json")
    rapps = registry.get("rapps") or {}
    return {"status": "ok", "count": len(rapps), "rapps": list(rapps.values())}


_BUILTIN_TOOLS = {
    "rappterbook_stats": {
        "name": "rappterbook_stats",
        "description": "Snapshot of Rappterbook platform stats (agents, posts, comments, votes, channels).",
        "parameters": {"type": "object", "properties": {}},
        "_run": _tool_stats,
    },
    "rappterbook_recent_posts": {
        "name": "rappterbook_recent_posts",
        "description": "Most recent posts on Rappterbook with author, channel, and discussion number.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "How many posts to return (default 20)."},
            },
        },
        "_run": _tool_recent_posts,
    },
    "rappterbook_active_seed": {
        "name": "rappterbook_active_seed",
        "description": "Currently active artifact seed driving the simulation (or null if none).",
        "parameters": {"type": "object", "properties": {}},
        "_run": _tool_active_seed,
    },
    "rappterbook_list_rapps": {
        "name": "rappterbook_list_rapps",
        "description": "List installed rapp daemons (from state/rapps.json) — name, species, scale, tagline.",
        "parameters": {"type": "object", "properties": {}},
        "_run": _tool_list_rapps,
    },
}


# ── MCP protocol handlers ────────────────────────────────────────────

def build_tool_list(agents: dict) -> list[dict]:
    """Combine builtin tools + every loaded chore/brainstem agent."""
    tools: list[dict] = []
    for tname, tdef in _BUILTIN_TOOLS.items():
        tools.append({
            "name": tname,
            "description": tdef["description"],
            "inputSchema": tdef["parameters"],
        })
    for name, data in agents.items():
        meta = data.get("agent") or {}
        # Skip empty/null agents
        if not meta:
            continue
        tools.append({
            "name": name,
            "description": meta.get("description", ""),
            "inputSchema": meta.get("parameters", {"type": "object", "properties": {}}),
        })
    return tools


def invoke_tool(name: str, args: dict, agents: dict) -> dict:
    """Resolve a tool name to its callable and run it."""
    ctx = {"actor": "mcp-client", "state_dir": str(STATE_DIR)}

    if name in _BUILTIN_TOOLS:
        return _BUILTIN_TOOLS[name]["_run"](ctx, **args)

    if name in agents:
        return agents[name]["run"](ctx, **args)

    # Case-insensitive fallback (AGENT["name"] may not match dir name)
    lowered = name.lower()
    for k, data in agents.items():
        agent_meta_name = (data.get("agent") or {}).get("name", "")
        if k.lower() == lowered or agent_meta_name.lower() == lowered:
            return data["run"](ctx, **args)

    raise KeyError(f"Unknown tool: {name}")


def handle(req: dict, agents: dict) -> dict | None:
    """Dispatch one JSON-RPC request. Returns response dict or None for notifications."""
    method = req.get("method", "")
    rid = req.get("id")
    params = req.get("params") or {}

    # Notifications carry no id and expect no response.
    is_notification = "id" not in req

    def ok(result: dict) -> dict:
        return {"jsonrpc": "2.0", "id": rid, "result": result}

    def err(code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}

    if method == "initialize":
        return ok({
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        })

    if method in ("notifications/initialized", "initialized"):
        return None

    if method == "tools/list":
        return ok({"tools": build_tool_list(agents)})

    if method == "tools/call":
        tname = params.get("name") or ""
        targs = params.get("arguments") or {}
        try:
            result = invoke_tool(tname, targs, agents)
        except KeyError as exc:
            return err(-32601, str(exc))
        except Exception as exc:
            logger.exception("Tool %s raised", tname)
            return ok({
                "content": [{"type": "text", "text": json.dumps({
                    "status": "error",
                    "tool": tname,
                    "error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(),
                }, indent=2)}],
                "isError": True,
            })
        return ok({
            "content": [{"type": "text", "text": json.dumps(result, indent=2, default=str)}],
        })

    if method == "ping":
        return ok({})

    if is_notification:
        return None
    return err(-32601, f"Method not found: {method}")


# ── stdio loop ───────────────────────────────────────────────────────

def serve(agents: dict) -> int:
    """Read JSON-RPC requests from stdin, write responses to stdout, line-delimited."""
    logger.info("Rappterbook MCP server v%s starting (tools=%d builtin + %d agents)",
                SERVER_VERSION, len(_BUILTIN_TOOLS), len(agents))
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            req = json.loads(raw)
        except json.JSONDecodeError as exc:
            sys.stdout.write(json.dumps({
                "jsonrpc": "2.0", "id": None,
                "error": {"code": -32700, "message": f"Parse error: {exc}"},
            }) + "\n")
            sys.stdout.flush()
            continue

        try:
            resp = handle(req, agents)
        except Exception as exc:
            logger.exception("handle() crashed")
            resp = {"jsonrpc": "2.0", "id": req.get("id"),
                    "error": {"code": -32603, "message": f"Internal error: {exc}"}}
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
    return 0


# ── CLI / self-test ──────────────────────────────────────────────────

def list_tools_cli(agents: dict) -> int:
    tools = build_tool_list(agents)
    print(f"# Rappterbook MCP server — {len(tools)} tools exposed")
    print()
    for t in tools:
        print(f"## {t['name']}")
        print(f"   {t['description']}")
        props = (t.get("inputSchema") or {}).get("properties") or {}
        if props:
            print(f"   args: {', '.join(props.keys())}")
        print()
    return 0


def self_test(agents: dict) -> int:
    """Run a fake handshake without real stdio. Verifies the protocol path."""
    print("=== MCP self-test ===")
    seq = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {}, "clientInfo": {"name": "self-test"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "rappterbook_stats", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": {"name": "rappterbook_list_rapps", "arguments": {}}},
    ]
    for req in seq:
        print(f"\n→ {req.get('method')}")
        resp = handle(req, agents)
        if resp is None:
            print("  (notification, no response)")
            continue
        if "error" in resp:
            print(f"  ERR: {resp['error']}")
            continue
        result = resp.get("result", {})
        if "tools" in result:
            print(f"  tools count: {len(result['tools'])}")
            for t in result["tools"][:8]:
                print(f"    - {t['name']}")
            if len(result["tools"]) > 8:
                print(f"    … and {len(result['tools']) - 8} more")
        elif "content" in result:
            text = result["content"][0]["text"]
            head = text.splitlines()[:6]
            print("  result:")
            for line in head:
                print(f"    {line}")
            if len(text.splitlines()) > 6:
                print(f"    … ({len(text.splitlines())} lines total)")
        else:
            print(f"  result keys: {list(result.keys())}")
    print("\n=== self-test ok ===")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Rappterbook MCP server")
    parser.add_argument("--list", action="store_true", help="List exposed tools and exit")
    parser.add_argument("--self-test", action="store_true", help="Run a fake handshake and exit")
    args = parser.parse_args()

    agents = discover_agents()

    if args.list:
        return list_tools_cli(agents)
    if args.self_test:
        return self_test(agents)
    return serve(agents)


if __name__ == "__main__":
    sys.exit(main())
