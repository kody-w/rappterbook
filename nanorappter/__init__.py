"""nanorappter — The anti-bloat agent runtime.

One file. Zero dependencies. Naive AI that just works.

    from nanorappter import NanoAgent, Gateway

    class MyBot(NanoAgent):
        def perform(self, event, detail):
            return {"reply": f"got {event}"}

    gw = Gateway()
    gw.register("my-bot", MyBot("my-bot", "Does things"))
    gw.notify("my-bot", "poke", {"from": "someone"})

OpenRappter: 1.8GB, 100+ deps, data sloshing, TypeScript build chain.
NanoRappter: 1 file, 0 deps, event → response, done.

Design principles:
  1. One file = one agent. No frameworks, no config files, no build steps.
  2. Zero dependencies. stdlib only. If you need requests, you don't need nanorappter.
  3. Events in, JSON out. That's the entire contract.
  4. Optional signal chaining (data_slush) — agents can pass signals downstream.
  5. Gateway is just a dict. No WebSocket servers, no message queues.
  6. Compatible with OpenRappter webhooks (JSON-RPC 2.0) but doesn't require it.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any


class NanoAgent:
    """Base class for all nanorappter agents. Override perform()."""

    def __init__(self, name: str, description: str = "", actions: list[str] | None = None):
        self.name = name
        self.description = description
        self.actions = actions or []
        self._log: list[dict] = []

    @property
    def metadata(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "actions": self.actions,
            "runtime": "nanorappter",
        }

    def perform(self, event: str, detail: dict) -> dict:
        """Handle an event. Override this. Return a dict."""
        raise NotImplementedError(f"{self.name} has no perform() implementation")

    def emit(self, **signals: Any) -> dict:
        """Create a data_slush envelope for downstream agents."""
        return {
            "source": self.name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "signals": signals,
        }

    def log(self, message: str) -> None:
        """Append to agent activity log."""
        entry = {"t": datetime.now(timezone.utc).isoformat(), "msg": message}
        self._log.append(entry)
        if len(self._log) > 100:
            self._log = self._log[-100:]

    def __repr__(self) -> str:
        return f"NanoAgent({self.name!r}, actions={self.actions})"


class Gateway:
    """Routes events to agents. That's it."""

    def __init__(self):
        self.agents: dict[str, NanoAgent] = {}

    def register(self, agent_id: str, agent: NanoAgent) -> None:
        self.agents[agent_id] = agent

    def unregister(self, agent_id: str) -> None:
        self.agents.pop(agent_id, None)

    def notify(self, agent_id: str, event: str, detail: dict | None = None) -> dict:
        """Send an event to an agent and return its response."""
        if agent_id not in self.agents:
            return {"error": f"agent not found: {agent_id}"}
        agent = self.agents[agent_id]
        if agent.actions and event not in agent.actions:
            return {"error": f"{agent_id} does not handle '{event}'", "supported": agent.actions}
        try:
            start = time.monotonic()
            result = agent.perform(event, detail or {})
            elapsed_ms = (time.monotonic() - start) * 1000
            if not isinstance(result, dict):
                result = {"result": result}
            result.setdefault("agent", agent_id)
            result.setdefault("event", event)
            result.setdefault("elapsed_ms", round(elapsed_ms, 1))
            agent.log(f"{event} → {result.get('status', 'ok')} ({elapsed_ms:.0f}ms)")
            return result
        except Exception as e:
            agent.log(f"{event} → ERROR: {e}")
            return {"error": str(e), "agent": agent_id, "event": event}

    def broadcast(self, event: str, detail: dict | None = None) -> list[dict]:
        """Send an event to ALL agents that handle it."""
        results = []
        for agent_id, agent in self.agents.items():
            if not agent.actions or event in agent.actions:
                results.append(self.notify(agent_id, event, detail))
        return results

    def chain(self, agent_ids: list[str], event: str, detail: dict | None = None) -> dict:
        """Pipeline: each agent's data_slush feeds into the next agent's detail."""
        current_detail = detail or {}
        last_result = {}
        for agent_id in agent_ids:
            last_result = self.notify(agent_id, event, current_detail)
            slush = last_result.get("data_slush", {})
            if isinstance(slush, dict):
                current_detail = {**current_detail, **slush}
        return last_result

    def handle_jsonrpc(self, body: dict) -> dict:
        """Handle OpenRappter-compatible JSON-RPC 2.0 calls."""
        rpc_id = body.get("id", 1)
        method = body.get("method", "")
        params = body.get("params", {})

        # Method format: "agent_id.event" or just "event" (broadcast)
        parts = method.rsplit(".", 1)
        if len(parts) == 2:
            agent_id, event = parts
            result = self.notify(agent_id, event, params)
        else:
            results = self.broadcast(parts[0], params)
            result = {"responses": results}

        return {"jsonrpc": "2.0", "result": result, "id": rpc_id}

    def status(self) -> dict:
        """Return gateway health."""
        return {
            "agents": {
                aid: {
                    "name": a.name,
                    "description": a.description,
                    "actions": a.actions,
                    "log_entries": len(a._log),
                    "last_activity": a._log[-1]["t"] if a._log else None,
                }
                for aid, a in self.agents.items()
            },
            "total": len(self.agents),
        }

    def __repr__(self) -> str:
        return f"Gateway({len(self.agents)} agents)"


# ── Convenience: HTTP gateway in 30 lines ───────────────────────────────
def serve(gateway: Gateway, port: int = 9999) -> None:
    """Start a minimal HTTP server for the gateway. Optional — not required."""
    from http.server import HTTPServer, BaseHTTPRequestHandler

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(gateway.status(), indent=2).encode())

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            if body.get("jsonrpc"):
                result = gateway.handle_jsonrpc(body)
            else:
                result = gateway.notify(
                    body.get("agent_id", ""),
                    body.get("event", ""),
                    body.get("detail", {}),
                )
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", port), Handler)
    print(f"nanorappter gateway → http://localhost:{port}  ({len(gateway.agents)} agents)")
    server.serve_forever()
