"""DriftSentinel — turns the snapshot audit harness into a continuous sentinel.

Compares the current audit report against the previous one (stored in
.brainstem/src/rapp_brainstem/.audit_history.json) and surfaces:
  * NEW regressions (was green, now red)
  * Newly-fixed tests (was red, now green)
  * Tests that stayed red across both runs
  * Tests that stayed green

This is the actual anti-gaslight machinery. The audit harness alone is a
snapshot; without DriftSentinel you can't tell if anything *changed* between
runs. With it, the twin can say "regression: governance lurks just dropped
to zero again, the fix didn't stick."
"""
import json
from datetime import datetime, timezone
from pathlib import Path

try:
    from agents.basic_agent import BasicAgent
except ImportError:
    from basic_agent import BasicAgent


HISTORY_PATH = Path(__file__).resolve().parent.parent / ".audit_history.json"
MAX_HISTORY = 50


def _load_history() -> dict:
    if not HISTORY_PATH.exists():
        return {"runs": []}
    try:
        with open(HISTORY_PATH) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"runs": []}


def _save_history(history: dict) -> None:
    history["runs"] = history.get("runs", [])[-MAX_HISTORY:]
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = HISTORY_PATH.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(history, f, indent=2)
    tmp.replace(HISTORY_PATH)


def _status_map(results: list) -> dict:
    return {r["test_id"]: r["status"] for r in results if "test_id" in r}


class DriftSentinelAgentAgent(BasicAgent):
    def __init__(self):
        self.name = "DriftSentinelAgent"
        self.metadata = {
            "name": self.name,
            "description": (
                "Stateful drift detector for the audit harness. Pass in the current "
                "audit report (structured output from AuditRunnerAgent) and this "
                "compares it to the previous one stored on disk. Returns the diff: "
                "new_regressions, new_fixes, still_red, still_green_count. Saves the "
                "current run as the new baseline unless no_save is true."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "current_report": {
                        "type": ["object", "string"],
                        "description": "The structured report from AuditRunnerAgent (dict or JSON string).",
                    },
                    "no_save": {
                        "type": "boolean",
                        "description": "If true, return the diff but do not update the saved baseline.",
                    },
                },
                "required": ["current_report"],
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, **kwargs):
        cur = kwargs.get("current_report")
        no_save = bool(kwargs.get("no_save", False))
        if isinstance(cur, str):
            try:
                cur = json.loads(cur)
            except json.JSONDecodeError:
                return json.dumps({"status": "error", "message": "current_report not valid JSON"})
        if not isinstance(cur, dict) or "results" not in cur:
            return json.dumps({
                "status": "error",
                "message": "current_report must be the dict returned by AuditRunnerAgent (with a 'results' field)",
            })

        history = _load_history()
        prev_run = history["runs"][-1] if history.get("runs") else None
        prev_results = (prev_run or {}).get("results", []) if prev_run else []
        prev_map = _status_map(prev_results)
        cur_map = _status_map(cur["results"])

        new_regressions = []
        new_fixes = []
        still_red = []
        still_green_count = 0
        for test_id, cur_status in cur_map.items():
            prev_status = prev_map.get(test_id)
            if prev_status == "green" and cur_status == "red":
                msg = ""
                for r in cur["results"]:
                    if r.get("test_id") == test_id:
                        msg = (r.get("assertion_message") or "")[:200]
                        break
                new_regressions.append({"test_id": test_id, "assertion": msg})
            elif prev_status == "red" and cur_status == "green":
                new_fixes.append(test_id)
            elif cur_status == "red":
                still_red.append(test_id)
            elif cur_status == "green":
                still_green_count += 1

        new_tests = [t for t in cur_map if t not in prev_map]
        dropped_tests = [t for t in prev_map if t not in cur_map]

        baseline_age = None
        if prev_run:
            try:
                prev_at = datetime.fromisoformat(prev_run["ran_at"].replace("Z", "+00:00"))
                baseline_age = round(
                    (datetime.now(timezone.utc) - prev_at).total_seconds() / 60, 1
                )
            except (KeyError, ValueError, AttributeError):
                pass

        if prev_run is None:
            verdict = "first_run"
        elif new_regressions:
            verdict = "drift_detected"
        elif still_red:
            verdict = "broken_but_stable"
        else:
            verdict = "stable"

        report = {
            "verdict": verdict,
            "compared_against_baseline_minutes_ago": baseline_age,
            "new_regressions": new_regressions,
            "new_fixes": new_fixes,
            "still_red": still_red,
            "still_green_count": still_green_count,
            "new_tests": new_tests,
            "dropped_tests": dropped_tests,
        }

        if not no_save:
            history.setdefault("runs", []).append({
                "ran_at": cur.get("ran_at") or datetime.now(timezone.utc).isoformat(),
                "summary": cur.get("summary", {}),
                "results": cur["results"],
            })
            _save_history(history)
            report["baseline_updated"] = True
        else:
            report["baseline_updated"] = False

        return json.dumps(report, indent=2)


if __name__ == "__main__":
    a = DriftSentinelAgentAgent()
    print(a.perform(current_report={"ran_at": "2026-05-22T19:00:00Z", "results": [], "summary": {}}))
