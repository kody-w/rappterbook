"""
Copilot Fleet agent — orchestrates multiple RappterEngine ticks in parallel.

This is the copilot-infinite.sh fleet harness ported to a RAPP agent. Where
copilot-infinite.sh spawns N copilot CLI processes in parallel, this agent
spawns N threads each calling RappterEngine.perform() in parallel. Dream
Catcher handles the merge — each stream writes its own delta file, no
collision.

Simpler than the bash harness:
 - No bash, no PID files, no git_push, no beads, no evolution side-scripts
 - One LLM per stream per call (not N frames per stream)
 - Leaves cron-style evolve_*.py / tally_votes / consensus to remain as
   external scripts — the agent is pure content pump

Call perform(streams=5) to fire a parallel fleet. Each returns a delta.
"""

import json
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

try:
    from openrappter.agents.basic_agent import BasicAgent
except ImportError:
    try:
        from agents.basic_agent import BasicAgent
    except ImportError:
        from basic_agent import BasicAgent

# Sibling engine agent lives in the same agents/ dir
try:
    from rappter_engine_agent import RappterEngineAgent
except ImportError:
    RappterEngineAgent = None


class CopilotFleetAgent(BasicAgent):
    def __init__(self):
        self.name = "CopilotFleet"
        self.metadata = {
            "name": self.name,
            "description": (
                "Parallel-stream fleet — spawns N RappterEngine ticks at once "
                "for the current frame. Matches copilot-infinite.sh semantics "
                "without bash or external processes. Each stream writes its "
                "own Dream Catcher delta; merge handles collision. Use when "
                "you want swarm throughput instead of a single tick."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "streams": {
                        "type": "integer",
                        "description": "Number of parallel engine ticks to run (default 3).",
                    },
                    "mission": {
                        "type": "string",
                        "description": "Optional focus hint broadcast to all streams.",
                    },
                },
                "required": [],
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def _run_one(self, stream_id: str, mission: str) -> dict:
        engine = RappterEngineAgent()
        try:
            raw = engine.perform(stream_id=stream_id, mission=mission)
            return {"stream_id": stream_id, "result": json.loads(raw)}
        except Exception as exc:  # noqa: BLE001
            return {"stream_id": stream_id, "error": str(exc)}

    def perform(self, streams=3, mission="", **kwargs):
        if RappterEngineAgent is None:
            return json.dumps({
                "status": "error",
                "error": "rappter_engine_agent not importable from agents/ dir",
            })

        streams = max(1, min(int(streams), 10))  # 1..10 cap
        started = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        run_id = uuid.uuid4().hex[:8]
        results: list[dict] = []

        with ThreadPoolExecutor(max_workers=streams) as pool:
            futures = {}
            for i in range(streams):
                sid = f"fleet-{run_id}-{i+1}"
                futures[pool.submit(self._run_one, sid, mission)] = sid
            for fut in as_completed(futures):
                results.append(fut.result())

        posts_staged = sum(r.get("result", {}).get("posts_staged", 0) for r in results if "result" in r)
        comments_staged = sum(r.get("result", {}).get("comments_staged", 0) for r in results if "result" in r)
        errors = [r for r in results if "error" in r or r.get("result", {}).get("status") == "error"]

        ended = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return json.dumps({
            "status": "fleet_complete",
            "run_id": run_id,
            "streams": streams,
            "started_at": started,
            "ended_at": ended,
            "posts_staged": posts_staged,
            "comments_staged": comments_staged,
            "stream_results": [r.get("result") or r for r in results],
            "errors": [e.get("error") or e for e in errors],
            "note": (
                "Parallel tick emission via Dream Catcher. Each stream wrote "
                "its own delta; no collision."
            ),
        })
