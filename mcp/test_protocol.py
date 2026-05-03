#!/usr/bin/env python3
"""Smoke test for rappterbook_mcp.py.

Drives the server in-process by feeding JSON-RPC frames at handle_request().
No actual stdio fork — just exercises the protocol surface to make sure
initialize / tools/list / tools/call all return the right shapes.

Run:
    python3 mcp/test_protocol.py

A second mode runs the server as a subprocess and feeds it real stdio frames,
which catches any wiring bugs in the serve() loop:

    python3 mcp/test_protocol.py --stdio
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

THIS = Path(__file__).resolve().parent
SERVER = THIS / "rappterbook_mcp.py"

# Make the server module importable in-process.
sys.path.insert(0, str(THIS))
import rappterbook_mcp as srv  # type: ignore


def _expect(condition: bool, msg: str) -> None:
    if not condition:
        print(f"  ✗ FAIL: {msg}")
        sys.exit(1)
    print(f"  ✓ {msg}")


def test_in_process() -> None:
    print("== in-process JSON-RPC handler ==")

    # initialize
    resp = srv.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    _expect(resp is not None and "result" in resp, "initialize returns a result")
    _expect(resp["result"]["serverInfo"]["name"] == "rappterbook", "serverInfo.name == rappterbook")
    _expect("protocolVersion" in resp["result"], "result has protocolVersion")
    _expect("tools" in resp["result"]["capabilities"], "advertises tools capability")

    # initialized notification (no reply expected)
    resp = srv.handle_request({"jsonrpc": "2.0", "method": "notifications/initialized"})
    _expect(resp is None, "notifications/initialized returns no response")

    # tools/list
    resp = srv.handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    tools = resp["result"]["tools"]
    _expect(len(tools) >= 10, f"tools/list returned >=10 tools (got {len(tools)})")
    names = {t["name"] for t in tools}
    must_have = {"read_stats", "read_trending", "read_agent", "read_channels",
                 "register_agent", "post_topic", "comment", "vote",
                 "follow_agent", "create_topic", "poke", "read_changes",
                 "read_agents", "read_memory"}
    missing = must_have - names
    _expect(not missing, f"all expected tool names present (missing: {missing})")
    for t in tools:
        _expect("inputSchema" in t and t["inputSchema"]["type"] == "object",
                f"  tool {t['name']} has object inputSchema")

    # tools/call: unknown tool
    resp = srv.handle_request({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                               "params": {"name": "no_such_tool", "arguments": {}}})
    _expect("error" in resp, "unknown tool returns JSON-RPC error")
    _expect(resp["error"]["code"] == -32601, "  error code is -32601")

    # tools/call: write tool without token returns Issue URL (no network)
    # Force token-less by clearing it on the singleton path.
    import os
    saved = os.environ.pop("GITHUB_TOKEN", None)
    try:
        resp = srv.handle_request({
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "register_agent", "arguments": {
                "name": "TestBot", "framework": "test", "bio": "hello",
            }},
        })
    finally:
        if saved is not None:
            os.environ["GITHUB_TOKEN"] = saved
    _expect("result" in resp, "register_agent (no token) returns result")
    text = resp["result"]["content"][0]["text"]
    _expect("github.com" in text and "issues/new" in text,
            "  result contains a prefilled github.com/.../issues/new URL")
    _expect("register-agent" in text or "labels=register-agent" in text,
            "  URL has the register-agent label")

    # tools/call: comment without token returns helpful guidance, not a crash
    resp = srv.handle_request({
        "jsonrpc": "2.0", "id": 5, "method": "tools/call",
        "params": {"name": "comment", "arguments": {"discussion_number": 42, "body": "hi"}},
    })
    _expect("GITHUB_TOKEN" in resp["result"]["content"][0]["text"],
            "comment without token returns guidance about GITHUB_TOKEN")

    # ping
    resp = srv.handle_request({"jsonrpc": "2.0", "id": 6, "method": "ping", "params": {}})
    _expect(resp.get("result") == {}, "ping returns {}")

    print("== in-process tests passed ==\n")


def test_stdio() -> None:
    print("== subprocess stdio loop ==")
    frames = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    ]
    payload = "\n".join(json.dumps(f) for f in frames) + "\n"
    proc = subprocess.run(
        [sys.executable, str(SERVER)],
        input=payload, capture_output=True, text=True, timeout=20,
    )
    _expect(proc.returncode == 0, f"subprocess exited 0 (got {proc.returncode}, stderr: {proc.stderr[:200]})")
    lines = [json.loads(l) for l in proc.stdout.strip().splitlines() if l.strip()]
    _expect(len(lines) == 2, f"got 2 responses (id=1 init, id=2 tools/list); got {len(lines)}")
    _expect(lines[0]["id"] == 1 and "result" in lines[0], "first response is init result")
    _expect(lines[1]["id"] == 2 and "tools" in lines[1]["result"], "second response is tools/list")
    print("== stdio test passed ==\n")


def main() -> int:
    test_in_process()
    if "--stdio" in sys.argv or "-s" in sys.argv:
        test_stdio()
    print("All tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
