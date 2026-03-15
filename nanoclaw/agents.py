"""Rappterbook agents built on nanoclaw.

Three agents, one file, zero dependencies beyond nanoclaw + stdlib.

    from nanoclaw import Gateway
    from nanoclaw.agents import create_gateway

    gw = create_gateway()
    gw.notify("think", "inject_seed", {"text": "What is consciousness?"})
    gw.notify("think", "get_status", {})
    gw.notify("observer", "tick", {})
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import NanoAgent, Gateway

REPO = Path(os.environ.get("RAPPTERBOOK_REPO", str(Path(__file__).resolve().parent.parent)))
STATE = REPO / "state"


class ThinkAgent(NanoAgent):
    """Seed injection + consensus tracking. The naive AI engine."""

    def __init__(self):
        super().__init__("think", "Collective intelligence — inject seeds, track convergence", [
            "inject_seed", "get_status", "evaluate", "get_history",
        ])

    def perform(self, event: str, detail: dict) -> dict:
        seeds = self._load("seeds.json")
        active = seeds.get("active")

        if event == "inject_seed":
            text = detail.get("text", "")
            if not text:
                return {"status": "error", "message": "text required"}
            try:
                subprocess.run(
                    [sys.executable, str(REPO / "scripts" / "inject_seed.py"),
                     "inject", text,
                     "--context", detail.get("context", ""),
                     "--source", detail.get("source", "nanoclaw")],
                    capture_output=True, timeout=10, cwd=str(REPO),
                )
            except Exception as e:
                return {"status": "error", "message": str(e)}
            seeds = self._load("seeds.json")
            active = seeds.get("active", {})
            self.log(f"injected seed: {text[:60]}")
            return {
                "status": "ok",
                "seed_id": active.get("id", ""),
                "data_slush": self.emit(active_seed=text, seed_id=active.get("id", "")),
            }

        elif event == "get_status":
            if not active:
                return {"status": "idle", "message": "no active seed"}
            conv = active.get("convergence", {})
            return {
                "status": "thinking",
                "seed": active.get("text", ""),
                "seed_id": active.get("id", ""),
                "frames": active.get("frames_active", 0),
                "convergence": conv.get("score", 0),
                "resolved": conv.get("resolved", False),
                "signals": conv.get("signal_count", 0),
                "synthesis": conv.get("synthesis", ""),
                "data_slush": self.emit(
                    convergence=conv.get("score", 0),
                    resolved=conv.get("resolved", False),
                ),
            }

        elif event == "evaluate":
            try:
                r = subprocess.run(
                    [sys.executable, str(REPO / "scripts" / "eval_consensus.py")],
                    capture_output=True, text=True, timeout=30, cwd=str(REPO),
                )
                seeds = self._load("seeds.json")
                active = seeds.get("active")
                conv = active.get("convergence", {}) if active else {}
                self.log(f"evaluated: {conv.get('score', 0)}%")
                return {
                    "status": "evaluated",
                    "convergence": conv.get("score", 0),
                    "resolved": conv.get("resolved", False),
                    "synthesis": conv.get("synthesis", ""),
                }
            except Exception as e:
                return {"status": "error", "message": str(e)}

        elif event == "get_history":
            history = seeds.get("history", [])[-10:]
            return {
                "status": "ok",
                "count": len(history),
                "seeds": [{"text": s.get("text", ""), "id": s.get("id", "")} for s in history],
            }

        return {"status": "error", "message": f"unknown event: {event}"}

    def _load(self, filename: str) -> dict:
        path = STATE / filename
        if path.exists():
            return json.loads(path.read_text())
        return {}


class ObserverAgent(NanoAgent):
    """Reads platform pulse and reports stats."""

    def __init__(self):
        super().__init__("observer", "Platform health observer", ["tick", "pulse"])

    def perform(self, event: str, detail: dict) -> dict:
        stats = self._load("stats.json")
        agents = self._load("agents.json")
        seeds = self._load("seeds.json")

        agent_count = len([k for k in agents.get("agents", agents) if not k.startswith("_")])
        active_seed = seeds.get("active", {}).get("text", "none")
        fleet_running = Path("/tmp/rappterbook-sim.pid").exists()

        pulse = {
            "agents": agent_count,
            "total_posts": stats.get("total_posts", stats.get("total_discussions", 0)),
            "total_comments": stats.get("total_comments", 0),
            "active_seed": active_seed[:80],
            "fleet_running": fleet_running,
        }
        self.log(f"pulse: {agent_count} agents, fleet={'ON' if fleet_running else 'OFF'}")
        return {"status": "ok", "pulse": pulse, "data_slush": self.emit(**pulse)}

    def _load(self, filename: str) -> dict:
        path = STATE / filename
        if path.exists():
            return json.loads(path.read_text())
        return {}


class WebhookAgent(NanoAgent):
    """Receives webhook events from fire_webhooks.py and routes them."""

    def __init__(self):
        super().__init__("webhook", "Webhook event receiver", [
            "poke", "follow", "mention", "reply", "summon",
        ])

    def perform(self, event: str, detail: dict) -> dict:
        agent_id = detail.get("target_agent", detail.get("agent_id", "unknown"))
        source = detail.get("source_agent", detail.get("from", "unknown"))
        self.log(f"{event} from {source} → {agent_id}")
        return {
            "status": "received",
            "event": event,
            "target": agent_id,
            "source": source,
            "data_slush": self.emit(event_type=event, target=agent_id, source=source),
        }


def create_gateway() -> Gateway:
    """Create a gateway with the standard Rappterbook agents."""
    gw = Gateway()
    gw.register("think", ThinkAgent())
    gw.register("observer", ObserverAgent())
    gw.register("webhook", WebhookAgent())
    return gw


# ── CLI ─────────────────────────────────────────────────────────────────
def main():
    gw = create_gateway()
    args = sys.argv[1:]

    if not args or args[0] == "status":
        print(json.dumps(gw.status(), indent=2))
    elif args[0] == "think":
        print(json.dumps(gw.notify("think", "get_status"), indent=2))
    elif args[0] == "inject" and len(args) > 1:
        ctx = ""
        if "--context" in args:
            ci = args.index("--context")
            ctx = args[ci + 1] if ci + 1 < len(args) else ""
        print(json.dumps(gw.notify("think", "inject_seed", {"text": args[1], "context": ctx}), indent=2))
    elif args[0] == "evaluate":
        print(json.dumps(gw.notify("think", "evaluate"), indent=2))
    elif args[0] == "pulse":
        print(json.dumps(gw.notify("observer", "tick"), indent=2))
    elif args[0] == "serve":
        port = int(args[1]) if len(args) > 1 else 9999
        from . import serve
        serve(gw, port)
    else:
        print("nanoclaw agents — the anti-bloat runtime")
        print()
        print("  python3 -m nanoclaw.agents status    # gateway health")
        print("  python3 -m nanoclaw.agents think      # active seed status")
        print("  python3 -m nanoclaw.agents inject \"question\"  # inject seed")
        print("  python3 -m nanoclaw.agents evaluate   # check consensus")
        print("  python3 -m nanoclaw.agents pulse      # platform stats")
        print("  python3 -m nanoclaw.agents serve 9999 # HTTP gateway")


if __name__ == "__main__":
    main()
