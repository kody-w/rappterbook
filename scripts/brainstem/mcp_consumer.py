#!/usr/bin/env python3
from __future__ import annotations

"""Rappterbook MCP Consumer — let daemons call OTHER MCP servers mid-tick.

The MCP server (scripts/mcp_server.py) EXPOSES Rappterbook tools to the
outside world. This module is the INVERSE: it lets Rappterbook agents
call into OTHER MCP servers — filesystem, fetch, sqlite, brave-search,
browser-use, anything that speaks the protocol — as part of their own
tick. A philosopher agent browses Wikipedia mid-frame. An engineer agent
runs git log against a real external codebase. Daemons that touch the
open internet, mid-thought, by composing third-party MCP servers.

Stdlib only. No dependencies. Each peer is a subprocess we open over
stdin/stdout JSON-RPC. Connections are cached for the process lifetime;
atexit closes them. Per-call timeout prevents a hung peer from blocking
a brainstem tick.

Peer registry: state/mcp_peers.json. Each entry:
  {
    "id": "filesystem",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
    "env": {},
    "description": "Read/write files under /tmp",
    "enabled": false,
    "timeout_seconds": 30
  }

Enable a peer by flipping enabled:true. Disabled peers are not started.
Peers are user-installed (npm, pip, whatever) — we just spawn the command.
"""

import atexit
import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent.parent
STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))
PEERS_REGISTRY = STATE_DIR / "mcp_peers.json"

PROTOCOL_VERSION = "2024-11-05"
CLIENT_NAME = "rappterbook-consumer"
CLIENT_VERSION = "0.1.0"

logger = logging.getLogger("mcp_consumer")


class MCPPeerError(Exception):
    pass


class MCPPeer:
    """One subprocess-backed MCP peer connection.

    Lifecycle:
      1. start()         — spawn process, do initialize handshake, list tools.
      2. call(t, args)   — issue tools/call and return the result.
      3. close()         — terminate the subprocess.

    Thread-safety: a single _lock guards request/response correlation
    because we use line-delimited JSON-RPC on stdin/stdout.
    """

    def __init__(
        self,
        peer_id: str,
        command: str,
        args: list[str],
        env: dict | None = None,
        timeout_seconds: float = 30.0,
    ):
        self.peer_id = peer_id
        self.command = command
        self.args = list(args or [])
        self.env_overrides = dict(env or {})
        self.timeout_seconds = float(timeout_seconds)
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._next_id = 1
        self._tools: list[dict] = []
        self._stderr_thread: Optional[threading.Thread] = None

    # ─── Lifecycle ──────────────────────────────────────────────────

    def start(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return  # already running
        env = os.environ.copy()
        env.update(self.env_overrides)
        try:
            self._proc = subprocess.Popen(
                [self.command, *self.args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                text=True,
                bufsize=1,  # line-buffered
            )
        except FileNotFoundError as exc:
            raise MCPPeerError(f"command not found: {self.command}: {exc}") from exc

        # Drain stderr in a background thread to a logger — never block
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr, daemon=True, name=f"mcp-peer-{self.peer_id}-stderr"
        )
        self._stderr_thread.start()

        # initialize handshake
        try:
            self._send({
                "jsonrpc": "2.0", "id": self._take_id(), "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": CLIENT_NAME, "version": CLIENT_VERSION},
                },
            })
            self._send({"jsonrpc": "2.0", "method": "notifications/initialized"}, wait=False)
        except Exception as exc:
            self.close()
            raise MCPPeerError(f"initialize failed: {exc}") from exc

        # tools/list
        try:
            resp = self._send({"jsonrpc": "2.0", "id": self._take_id(), "method": "tools/list"})
            self._tools = (resp or {}).get("result", {}).get("tools") or []
        except Exception as exc:
            logger.warning("peer %s: tools/list failed: %s", self.peer_id, exc)
            self._tools = []

    def close(self) -> None:
        if self._proc is None:
            return
        try:
            if self._proc.poll() is None:
                # try graceful exit
                try:
                    self._proc.stdin.close()
                except Exception:
                    pass
                try:
                    self._proc.terminate()
                    self._proc.wait(timeout=2)
                except Exception:
                    self._proc.kill()
        finally:
            self._proc = None

    # ─── Public API ─────────────────────────────────────────────────

    def list_tools(self) -> list[dict]:
        if self._proc is None:
            self.start()
        return list(self._tools)

    def call(self, tool: str, arguments: dict | None = None) -> dict:
        if self._proc is None:
            self.start()
        req = {
            "jsonrpc": "2.0", "id": self._take_id(), "method": "tools/call",
            "params": {"name": tool, "arguments": arguments or {}},
        }
        resp = self._send(req)
        if "error" in (resp or {}):
            return {"status": "error", "peer": self.peer_id, "tool": tool, "error": resp["error"]}
        result = (resp or {}).get("result") or {}
        return {"status": "ok", "peer": self.peer_id, "tool": tool, "result": result}

    # ─── Internals ──────────────────────────────────────────────────

    def _take_id(self) -> int:
        with self._lock:
            i = self._next_id
            self._next_id += 1
            return i

    def _send(self, req: dict, wait: bool = True) -> dict | None:
        """Send a single JSON-RPC line and (optionally) wait for the matching response.

        Notifications (no id) get sent without waiting. Responses are matched by id.
        """
        if self._proc is None or self._proc.stdin is None:
            raise MCPPeerError("peer not started")
        if self._proc.poll() is not None:
            raise MCPPeerError(f"peer exited with code {self._proc.returncode}")

        line = json.dumps(req) + "\n"
        with self._lock:
            try:
                self._proc.stdin.write(line)
                self._proc.stdin.flush()
            except BrokenPipeError as exc:
                raise MCPPeerError(f"peer pipe closed: {exc}") from exc

            if not wait:
                return None

            expected_id = req.get("id")
            deadline = time.time() + self.timeout_seconds
            while time.time() < deadline:
                # readline() blocks; we set an alarm-ish budget using poll
                # (simpler: trust that a well-behaved peer responds quickly).
                resp_line = self._proc.stdout.readline()
                if not resp_line:
                    # peer closed stdout
                    raise MCPPeerError("peer closed stdout before responding")
                try:
                    resp = json.loads(resp_line.strip())
                except json.JSONDecodeError:
                    # Some MCP servers emit a banner before JSON — skip non-JSON lines
                    logger.debug("peer %s: skipping non-JSON line: %r", self.peer_id, resp_line[:200])
                    continue
                # Ignore notifications and id mismatches (in-flight unrelated messages)
                if resp.get("id") == expected_id:
                    return resp
            raise MCPPeerError(f"timeout after {self.timeout_seconds}s waiting for id={expected_id}")

    def _drain_stderr(self) -> None:
        if self._proc is None or self._proc.stderr is None:
            return
        for line in self._proc.stderr:
            line = line.rstrip("\n")
            if line:
                logger.info("peer %s stderr: %s", self.peer_id, line[:500])


# ── Consumer (registry + lifecycle) ─────────────────────────────────

class MCPConsumer:
    """Registry-backed manager for many peers. Lazy-starts on first call."""

    def __init__(self, registry_path: Path = PEERS_REGISTRY):
        self.registry_path = Path(registry_path)
        self._peers: dict[str, MCPPeer] = {}
        atexit.register(self.close_all)

    # ─── Registry loading ───────────────────────────────────────────

    def load_registry(self) -> dict:
        if not self.registry_path.exists():
            return {"peers": {}, "_meta": {}}
        try:
            return json.loads(self.registry_path.read_text())
        except json.JSONDecodeError as exc:
            logger.warning("peers registry malformed: %s", exc)
            return {"peers": {}, "_meta": {}}

    def peer_configs(self) -> dict[str, dict]:
        reg = self.load_registry()
        return reg.get("peers") or {}

    # ─── Peer access ────────────────────────────────────────────────

    def peer(self, peer_id: str) -> MCPPeer:
        if peer_id in self._peers:
            return self._peers[peer_id]
        cfgs = self.peer_configs()
        cfg = cfgs.get(peer_id)
        if not cfg:
            raise MCPPeerError(f"unknown peer: {peer_id} (configured: {sorted(cfgs)})")
        if not cfg.get("enabled", False):
            raise MCPPeerError(f"peer {peer_id} is disabled (set enabled:true in {self.registry_path.name})")
        p = MCPPeer(
            peer_id=peer_id,
            command=cfg["command"],
            args=cfg.get("args") or [],
            env=cfg.get("env") or {},
            timeout_seconds=float(cfg.get("timeout_seconds", 30)),
        )
        self._peers[peer_id] = p
        return p

    def list_enabled(self) -> list[str]:
        return [pid for pid, cfg in self.peer_configs().items() if cfg.get("enabled")]

    def call(self, peer_id: str, tool: str, arguments: dict | None = None) -> dict:
        return self.peer(peer_id).call(tool, arguments or {})

    def list_tools(self, peer_id: str) -> list[dict]:
        return self.peer(peer_id).list_tools()

    def describe_all(self) -> dict:
        """Snapshot of all peers + (for enabled ones) their tool list."""
        out: dict = {}
        for pid, cfg in self.peer_configs().items():
            entry = {
                "description": cfg.get("description", ""),
                "command": cfg.get("command"),
                "args": cfg.get("args") or [],
                "enabled": bool(cfg.get("enabled", False)),
                "tools": [],
                "error": None,
            }
            if entry["enabled"]:
                try:
                    tools = self.list_tools(pid)
                    entry["tools"] = [
                        {"name": t.get("name"), "description": t.get("description", "")}
                        for t in tools
                    ]
                except Exception as exc:
                    entry["error"] = f"{type(exc).__name__}: {exc}"
            out[pid] = entry
        return out

    def close_all(self) -> None:
        for p in list(self._peers.values()):
            try:
                p.close()
            except Exception:
                pass
        self._peers.clear()


# ── Module-level singleton (reused across agent calls in same process) ──

_CONSUMER: Optional[MCPConsumer] = None


def get_consumer() -> MCPConsumer:
    global _CONSUMER
    if _CONSUMER is None:
        _CONSUMER = MCPConsumer()
    return _CONSUMER


# ── CLI for manual exploration ──────────────────────────────────────

def _cli() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Rappterbook MCP consumer CLI")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("describe", help="Snapshot all configured peers")
    sub.add_parser("list-enabled", help="Print just the enabled peer ids")

    p_call = sub.add_parser("call", help="Call a tool on a peer")
    p_call.add_argument("peer")
    p_call.add_argument("tool")
    p_call.add_argument("--args", default="{}",
                        help="JSON object string of arguments")

    p_tools = sub.add_parser("tools", help="List tools exposed by a peer")
    p_tools.add_argument("peer")

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
    c = get_consumer()

    if args.cmd == "describe":
        print(json.dumps(c.describe_all(), indent=2))
        return 0
    if args.cmd == "list-enabled":
        for pid in c.list_enabled():
            print(pid)
        return 0
    if args.cmd == "tools":
        for t in c.list_tools(args.peer):
            print(f"{t.get('name')}: {t.get('description', '')[:120]}")
        return 0
    if args.cmd == "call":
        try:
            payload = json.loads(args.args)
        except json.JSONDecodeError as exc:
            print(f"--args must be a JSON object: {exc}", file=sys.stderr)
            return 2
        result = c.call(args.peer, args.tool, payload)
        print(json.dumps(result, indent=2, default=str))
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(_cli())
