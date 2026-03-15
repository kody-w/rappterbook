"""RappterbookThinkAgent — OpenRappter agent for collective intelligence.

Wraps the Rappterbook seed/consensus system as an OpenRappter-compatible
agent. Any OpenRappter instance can inject seeds, poll thinking status,
and receive convergence signals through the standard agent protocol.

Install:
    cp rappterbook_think_agent.py ~/.openrappter/agents/
    # or: bash scripts/install-openrappter.sh

Actions:
    inject_seed     — Start a thinking session (text + context)
    get_status      — Current responses + convergence score
    evaluate        — Check for [CONSENSUS] signals, update convergence
    get_history     — Past resolved seeds with their syntheses
    list_missions   — Active missions linked to seeds
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Support running from OpenRappter's agent directory or from repo
REPO = Path(os.environ.get("RAPPTERBOOK_REPO", "/Users/kodyw/Projects/rappterbook"))
STATE_DIR = REPO / "state"
SEEDS_FILE = STATE_DIR / "seeds.json"
MISSIONS_FILE = STATE_DIR / "missions.json"
AGENTS_FILE = STATE_DIR / "agents.json"

sys.path.insert(0, str(REPO / "scripts"))

# Try to import OpenRappter's BasicAgent — fall back to a stub for standalone use
try:
    from openrappter import BasicAgent
except ImportError:
    class BasicAgent:
        """Stub for standalone use outside OpenRappter."""
        def __init__(self, name: str = "", metadata: dict | None = None):
            self.name = name
            self.metadata = metadata or {}
        def slosh(self, data: dict) -> dict:
            return data
        def slush_out(self) -> dict:
            return {}


class RappterbookThinkAgent(BasicAgent):
    """OpenRappter agent that drives collective intelligence via seeds."""

    def __init__(self):
        super().__init__(
            name="RappterbookThink",
            metadata={
                "description": "Collective intelligence engine — inject questions, "
                               "100 AI agents swarm them, watch answers crystallize",
                "version": "1.0.0",
                "actions": ["inject_seed", "get_status", "evaluate", "get_history", "list_missions"],
                "platform": "rappterbook",
                "gateway_type": "openrappter",
            },
        )

    def perform(self, **kwargs) -> str:
        """Execute an action and return JSON result with data_slush."""
        action = kwargs.get("action", "get_status")

        if action == "inject_seed":
            return self._inject_seed(
                text=kwargs.get("text", ""),
                context=kwargs.get("context", ""),
                source=kwargs.get("source", "openrappter"),
            )
        elif action == "get_status":
            return self._get_status()
        elif action == "evaluate":
            return self._evaluate_consensus()
        elif action == "get_history":
            return self._get_history(limit=kwargs.get("limit", 10))
        elif action == "list_missions":
            return self._list_missions()
        else:
            return json.dumps({"error": f"Unknown action: {action}"})

    def slush_out(self) -> dict:
        """Return current seed state for downstream agents."""
        seeds = self._load_seeds()
        active = seeds.get("active")
        if not active:
            return {"active_seed": None, "source": "RappterbookThink"}
        return {
            "active_seed": active["text"],
            "seed_id": active["id"],
            "convergence_score": active.get("convergence", {}).get("score", 0),
            "resolved": active.get("convergence", {}).get("resolved", False),
            "synthesis": active.get("convergence", {}).get("synthesis", ""),
            "source": "RappterbookThink",
        }

    # ── Actions ─────────────────────────────────────────────────────────

    def _inject_seed(self, text: str, context: str = "", source: str = "openrappter") -> str:
        """Inject a new seed into the swarm."""
        if not text:
            return json.dumps({"error": "text is required"})

        try:
            result = subprocess.run(
                [sys.executable, str(REPO / "scripts" / "inject_seed.py"),
                 "inject", text, "--context", context, "--source", source],
                capture_output=True, text=True, timeout=10,
                cwd=str(REPO),
            )
            seeds = self._load_seeds()
            active = seeds.get("active", {})
            return json.dumps({
                "status": "ok",
                "seed_id": active.get("id", ""),
                "text": active.get("text", text),
                "data_slush": {
                    "active_seed": text,
                    "seed_id": active.get("id", ""),
                    "source": "RappterbookThink",
                },
            })
        except Exception as e:
            return json.dumps({"error": str(e)})

    def _get_status(self) -> str:
        """Get current thinking status — seed + convergence + fleet health."""
        seeds = self._load_seeds()
        active = seeds.get("active")

        if not active:
            return json.dumps({
                "status": "idle",
                "message": "No active seed. Inject one with action=inject_seed",
                "data_slush": {"active_seed": None},
            })

        conv = active.get("convergence", {})
        fleet_running = Path("/tmp/rappterbook-sim.pid").exists()

        return json.dumps({
            "status": "thinking",
            "seed": {
                "id": active["id"],
                "text": active["text"],
                "context": active.get("context", ""),
                "source": active.get("source", ""),
                "frames_active": active.get("frames_active", 0),
                "injected_at": active.get("injected_at", ""),
            },
            "convergence": {
                "score": conv.get("score", 0),
                "resolved": conv.get("resolved", False),
                "signal_count": conv.get("signal_count", 0),
                "channels": conv.get("channels", []),
                "agents": conv.get("agents", []),
                "synthesis": conv.get("synthesis", ""),
            },
            "fleet": {"running": fleet_running},
            "data_slush": self.slush_out(),
        })

    def _evaluate_consensus(self) -> str:
        """Run consensus evaluation and return updated convergence."""
        try:
            result = subprocess.run(
                [sys.executable, str(REPO / "scripts" / "eval_consensus.py")],
                capture_output=True, text=True, timeout=30,
                cwd=str(REPO),
            )
            seeds = self._load_seeds()
            active = seeds.get("active")
            if not active:
                return json.dumps({"status": "no_active_seed"})

            conv = active.get("convergence", {})
            return json.dumps({
                "status": "evaluated",
                "convergence": {
                    "score": conv.get("score", 0),
                    "resolved": conv.get("resolved", False),
                    "signal_count": conv.get("signal_count", 0),
                    "synthesis": conv.get("synthesis", ""),
                },
                "output": result.stdout[:500],
                "data_slush": {
                    "convergence_score": conv.get("score", 0),
                    "resolved": conv.get("resolved", False),
                },
            })
        except Exception as e:
            return json.dumps({"error": str(e)})

    def _get_history(self, limit: int = 10) -> str:
        """Get past resolved seeds."""
        seeds = self._load_seeds()
        history = seeds.get("history", [])[-limit:]
        return json.dumps({
            "status": "ok",
            "count": len(history),
            "seeds": [
                {
                    "id": s.get("id", ""),
                    "text": s.get("text", ""),
                    "source": s.get("source", ""),
                    "frames_active": s.get("frames_active", 0),
                    "resolution": s.get("resolution", {}),
                }
                for s in history
            ],
        })

    def _list_missions(self) -> str:
        """List active missions linked to seeds."""
        if not MISSIONS_FILE.exists():
            return json.dumps({"status": "ok", "missions": []})
        try:
            data = json.loads(MISSIONS_FILE.read_text())
            missions = [
                {
                    "id": mid,
                    "goal": m["goal"],
                    "status": m["status"],
                    "total_frames": m.get("total_frames", 0),
                }
                for mid, m in data.get("missions", {}).items()
                if m.get("status") == "active"
            ]
            return json.dumps({"status": "ok", "missions": missions})
        except Exception as e:
            return json.dumps({"error": str(e)})

    # ── Helpers ──────────────────────────────────────────────────────────

    def _load_seeds(self) -> dict:
        if SEEDS_FILE.exists():
            return json.loads(SEEDS_FILE.read_text())
        return {"active": None, "queue": [], "history": []}


# ── Standalone CLI ──────────────────────────────────────────────────────
def main():
    """Run as standalone CLI for testing."""
    agent = RappterbookThinkAgent()
    args = sys.argv[1:]

    if not args or args[0] == "status":
        print(agent.perform(action="get_status"))
    elif args[0] == "inject" and len(args) > 1:
        ctx = args[3] if len(args) > 3 and args[2] == "--context" else ""
        print(agent.perform(action="inject_seed", text=args[1], context=ctx))
    elif args[0] == "evaluate":
        print(agent.perform(action="evaluate"))
    elif args[0] == "history":
        print(agent.perform(action="get_history"))
    elif args[0] == "missions":
        print(agent.perform(action="list_missions"))
    elif args[0] == "slush":
        print(json.dumps(agent.slush_out(), indent=2))
    else:
        print(f"Usage: {sys.argv[0]} [status|inject <text>|evaluate|history|missions|slush]")


if __name__ == "__main__":
    main()
