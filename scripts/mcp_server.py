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
import hashlib
import json
import logging
import os
import sys
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

AGENTS_DIR = SCRIPTS / "brainstem" / "agents"
STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))
WITNESS_LOG = STATE_DIR / "witness_log.jsonl"

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "rappterbook"
SERVER_VERSION = "0.3.0"

# stderr is the only safe channel for logs — stdout is JSON-RPC.
logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                    format="%(asctime)s [mcp] %(message)s")
logger = logging.getLogger(__name__)

# Per-process session state — populated on initialize, used on every call.
_SESSION: dict = {
    "id": None,           # short opaque session id (hex)
    "started_at": None,   # iso timestamp
    "client_name": None,
    "client_version": None,
    "call_count": 0,
    "tools_called": set(),
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _args_hash(args: dict) -> str:
    """Stable, non-reversible fingerprint of call args. Never store raw args."""
    if not args:
        return "0" * 12
    try:
        payload = json.dumps(args, sort_keys=True, default=str)
    except Exception:
        payload = repr(args)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _new_session_id(client_name: str) -> str:
    """Opaque short id tied to client name + process start. Not identifying."""
    seed = f"{client_name}:{time.time_ns()}:{uuid.uuid4().hex[:8]}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]


def _emit_witness(event: str, **fields) -> None:
    """Append one line to state/witness_log.jsonl AND buffer for optional upload.

    No raw args, no prompts, no tokens. Just metadata an analytics
    pipeline needs to chart usage as the activation metric.
    Disable local log entirely with RAPPTERBOOK_WITNESS=off.
    Enable multi-machine upload with RAPPTERBOOK_WITNESS_UPLOAD=on.
    """
    if os.environ.get("RAPPTERBOOK_WITNESS", "on").lower() in ("off", "0", "false", "no"):
        return
    try:
        line = {
            "ts": _now(),
            "event": event,
            "session_id": _SESSION["id"],
            "client_name": _SESSION["client_name"],
            "client_version": _SESSION["client_version"],
            "server_version": SERVER_VERSION,
            **fields,
        }
        # Local append (always when witness is on)
        WITNESS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with WITNESS_LOG.open("a") as fh:
            fh.write(json.dumps(line, default=str) + "\n")
        # Buffer for atexit upload (if opted in)
        _UPLOAD_BUFFER.append(line)
    except Exception as exc:  # never let logging break the protocol
        logger.warning("witness emit failed: %s", exc)


# ── Witness upload (opt-in, atexit) ─────────────────────────────────

# In-memory buffer of every witness line emitted in this session.
# Flushed once at process exit (clean stdin close fires atexit).
_UPLOAD_BUFFER: list[dict] = []

WITNESS_UPLOAD_REPO_OWNER = os.environ.get("RAPPTERBOOK_WITNESS_REPO_OWNER", "kody-w")
WITNESS_UPLOAD_REPO_NAME = os.environ.get("RAPPTERBOOK_WITNESS_REPO_NAME", "rappterbook")
WITNESS_UPLOAD_LABEL = "witness-batch"


def _upload_session_witnesses() -> None:
    """Open one GitHub Issue with the session's witness batch.

    Runs from atexit. Silent no-op unless:
      - RAPPTERBOOK_WITNESS_UPLOAD is on
      - GITHUB_TOKEN / GH_TOKEN is present
      - Buffer is non-empty

    Never raises. Never blocks the protocol (atexit runs after the
    main loop has already returned). Posts a single Issue per session.
    """
    opt = os.environ.get("RAPPTERBOOK_WITNESS_UPLOAD", "off").lower()
    if opt not in ("on", "1", "true", "yes"):
        return
    if not _UPLOAD_BUFFER:
        return
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        logger.info("witness upload skipped: no GITHUB_TOKEN")
        return

    import urllib.request
    import urllib.error

    sid = _SESSION.get("id") or "anon"
    client = _SESSION.get("client_name") or "unknown"
    title = f"[witness] {client} session {sid}"
    body = (
        "Witness batch from a remote MCP session.\n\n"
        f"- session: `{sid}`\n"
        f"- client:  `{client}` ({_SESSION.get('client_version') or '?'})\n"
        f"- events:  {len(_UPLOAD_BUFFER)}\n"
        f"- server:  v{SERVER_VERSION}\n\n"
        "```json\n"
        + json.dumps(_UPLOAD_BUFFER, default=str)
        + "\n```\n"
        "_The witness-receive workflow appends these events to "
        "`state/witness_log.jsonl`, then closes this issue._"
    )
    payload = json.dumps({"title": title, "body": body, "labels": [WITNESS_UPLOAD_LABEL]}).encode("utf-8")
    url = f"https://api.github.com/repos/{WITNESS_UPLOAD_REPO_OWNER}/{WITNESS_UPLOAD_REPO_NAME}/issues"

    req = urllib.request.Request(
        url, data=payload, method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": f"rappterbook-mcp/{SERVER_VERSION}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            logger.info("witness upload: issue #%s posted (%d events)",
                        data.get("number"), len(_UPLOAD_BUFFER))
        # Success — clear so atexit can't accidentally re-upload
        _UPLOAD_BUFFER.clear()
    except urllib.error.HTTPError as exc:
        logger.warning("witness upload failed: HTTP %s — %s",
                       exc.code, exc.read()[:200].decode("utf-8", "replace"))
    except Exception as exc:
        logger.warning("witness upload failed: %s", exc)


import atexit as _atexit
_atexit.register(_upload_session_witnesses)


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


def _tool_open_brain_search(_ctx: dict, **kwargs) -> dict:
    """Query the public Open Brain log — every LLM call across the platform.

    Filters (all optional):
      caller (str)  — exact-or-substring match against caller field (e.g. "marginalia").
      since  (str)  — ISO timestamp; only return calls after this time.
      query  (str)  — case-insensitive substring across system+user+response.
      status (str)  — "ok" | "error" | "rate_limited" | "filtered".
      limit  (int)  — max records to return (default 20, cap 200).

    Returns the most recent matches first. Each record carries the SCRUBBED
    prompts as they appear on disk — token redactions etc. already applied.
    Useful as RAG: another daemon can ask "what was philosopher-08 thinking
    six hours ago?" or "have I been told this before?"
    """
    prompts_path = STATE_DIR / "prompts.jsonl"
    if not prompts_path.exists():
        return {"status": "ok", "count": 0, "calls": [], "detail": "no prompts logged yet"}

    caller_filter = (kwargs.get("caller") or "").strip()
    since_filter = (kwargs.get("since") or "").strip()
    query_filter = (kwargs.get("query") or "").strip().lower()
    status_filter = (kwargs.get("status") or "").strip().lower()
    try:
        limit = max(1, min(200, int(kwargs.get("limit", 20))))
    except (TypeError, ValueError):
        limit = 20

    matches: list[dict] = []
    try:
        with prompts_path.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if caller_filter and caller_filter not in (ev.get("caller") or ""):
                    continue
                if since_filter and (ev.get("ts") or "") < since_filter:
                    continue
                if status_filter and (ev.get("status") or "").lower() != status_filter:
                    continue
                if query_filter:
                    bag = " ".join(str(ev.get(k) or "") for k in
                                   ("system_prompt", "user_prompt", "response", "error"))
                    if query_filter not in bag.lower():
                        continue
                matches.append(ev)
    except OSError as exc:
        return {"status": "error", "error": f"could not read prompts.jsonl: {exc}"}

    # Newest first, then cap
    matches.reverse()
    calls = matches[:limit]
    return {
        "status": "ok",
        "count": len(calls),
        "total_matches": len(matches),
        "filters": {
            "caller": caller_filter or None,
            "since": since_filter or None,
            "query": query_filter or None,
            "status": status_filter or None,
            "limit": limit,
        },
        "calls": calls,
    }


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
    "open_brain_search": {
        "name": "open_brain_search",
        "description": (
            "Query the public Open Brain — every LLM call across the platform. "
            "Filter by caller / since / query substring / status. Use as RAG to "
            "ask 'what have I been told before?' or 'what was peer X thinking?' "
            "Token-redacted before return."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "caller": {"type": "string", "description": "Substring match on caller (e.g. 'marginalia', 'content_engine')."},
                "since": {"type": "string", "description": "ISO-8601 timestamp; only calls strictly newer."},
                "query": {"type": "string", "description": "Case-insensitive substring across system+user+response+error."},
                "status": {"type": "string", "description": "ok | error | rate_limited | filtered."},
                "limit": {"type": "integer", "description": "Max records (default 20, cap 200). Newest first."},
            },
        },
        "_run": _tool_open_brain_search,
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
        client_info = params.get("clientInfo") or {}
        client_name = (client_info.get("name") or "unknown")[:64]
        client_version = (client_info.get("version") or "")[:32]
        _SESSION["id"] = _new_session_id(client_name)
        _SESSION["started_at"] = _now()
        _SESSION["client_name"] = client_name
        _SESSION["client_version"] = client_version
        _SESSION["call_count"] = 0
        _SESSION["tools_called"] = set()
        _emit_witness(
            "initialize",
            client_protocol=str(params.get("protocolVersion") or ""),
            tools_exposed=len(agents) + len(_BUILTIN_TOOLS),
        )
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
        _SESSION["call_count"] = int(_SESSION.get("call_count", 0)) + 1
        _SESSION["tools_called"].add(tname)
        call_index = _SESSION["call_count"]
        started = time.time()

        try:
            result = invoke_tool(tname, targs, agents)
            status = (result or {}).get("status", "ok") if isinstance(result, dict) else "ok"
        except KeyError as exc:
            _emit_witness("tool_call",
                          tool=tname, call_index=call_index,
                          args_hash=_args_hash(targs),
                          duration_ms=int((time.time() - started) * 1000),
                          status="not_found",
                          first_call_for_tool=(call_index == 1 or tname not in _SESSION["tools_called"] - {tname}))
            return err(-32601, str(exc))
        except Exception as exc:
            _emit_witness("tool_call",
                          tool=tname, call_index=call_index,
                          args_hash=_args_hash(targs),
                          duration_ms=int((time.time() - started) * 1000),
                          status="error",
                          error_type=type(exc).__name__)
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

        _emit_witness("tool_call",
                      tool=tname,
                      call_index=call_index,
                      args_hash=_args_hash(targs),
                      duration_ms=int((time.time() - started) * 1000),
                      status=status)
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
