"""twin_of_twins_meta_watcher_agent.py — verifier of verifiers.

Reads the last N output records from each known observer twin and asks
Copilot CLI to judge whether each twin is still doing its job. Catches
the failure mode where a verifier degenerates silently.
"""
from __future__ import annotations
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    from agents.basic_agent import BasicAgent
except ImportError:
    from basic_agent import BasicAgent


OUT_DIR = Path("/tmp/twin-of-twins-meta-watcher")
SOUL_PATH = Path(__file__).resolve().parent.parent / "soul.md"

TWINS_TO_WATCH = [
    {"name": "KodyBabysitter",       "glob": "/tmp/kody-babysitter/watch-*.json",
     "expected_keys": ["verdict", "findings_summary"]},
    {"name": "AuthenticityTwin",     "glob": "/tmp/authenticity-twin/scan-*.json",
     "expected_keys": ["overall_sim_verdict", "avg_authenticity_score", "per_post_scores"]},
    {"name": "NormieAITwin",         "glob": "/tmp/normie-ai-twin/scan-*.json",
     "expected_keys": ["platform_passes_receptiveness_test", "per_persona_reports"]},
    {"name": "MutationEfficacyTwin", "glob": "/tmp/mutation-efficacy-twin/scan-*.json",
     "expected_keys": ["verdict", "key_metrics"]},
]


def _summarize_twin(twin_meta: dict, last_n: int = 10) -> dict:
    """Read the last N records for one twin, extract enough for the LLM to judge."""
    import glob
    files = sorted(glob.glob(twin_meta["glob"]))[-last_n:]
    summary = {
        "name": twin_meta["name"], "n_records": len(files),
        "samples": [], "verdict_distribution": {}, "first_record_ts": None,
        "last_record_ts": None,
    }
    if not files:
        summary["status_inference"] = "no_records_found"
        return summary
    summary["first_record_ts"] = datetime.fromtimestamp(
        Path(files[0]).stat().st_mtime, timezone.utc).isoformat()
    summary["last_record_ts"] = datetime.fromtimestamp(
        Path(files[-1]).stat().st_mtime, timezone.utc).isoformat()

    # Extract per-record digest: just the headline + key counts
    for f in files:
        try:
            rec = json.loads(Path(f).read_text())
        except Exception:
            summary["samples"].append({"file": Path(f).name, "error": "bad_json"})
            continue
        digest = {"file": Path(f).name}
        for k in twin_meta["expected_keys"]:
            if k in rec:
                v = rec[k]
                if isinstance(v, (str, int, float, bool)) or v is None:
                    digest[k] = v
                elif isinstance(v, dict):
                    digest[k + "_keys"] = list(v.keys())[:5]
                    digest[k + "_summary"] = str(v)[:200]
                elif isinstance(v, list):
                    digest[k + "_len"] = len(v)
        # Tally verdict-like fields for distribution
        for vk in ("verdict", "overall_sim_verdict", "platform_passes_receptiveness_test"):
            if vk in rec:
                val = str(rec[vk])
                summary["verdict_distribution"][val] = summary["verdict_distribution"].get(val, 0) + 1
        summary["samples"].append(digest)
    return summary


class TwinOfTwinsMetaWatcherAgent(BasicAgent):
    def __init__(self):
        self.name = "TwinOfTwinsMetaWatcher"
        self.metadata = {
            "name": self.name,
            "description": (
                "Verifier of verifiers. Reads the last N output records from "
                "each known observer twin (KodyBabysitter, AuthenticityTwin, "
                "NormieAITwin, MutationEfficacyTwin) and judges via Copilot CLI "
                "whether each twin is still doing its job honestly. Verdicts: "
                "healthy | stuck | degraded | crashed. Closes the 'who watches "
                "the watchers' recursion."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "last_n": {
                        "type": "integer",
                        "description": "How many recent records per twin to analyze (default 10).",
                    },
                },
                "required": [],
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, **kwargs):
        last_n = int(kwargs.get("last_n", 10))
        last_n = max(3, min(last_n, 50))
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        frame_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")

        twin_summaries = [_summarize_twin(t, last_n) for t in TWINS_TO_WATCH]

        try:
            soul_text = SOUL_PATH.read_text()
        except Exception:
            soul_text = "You are the Twin-of-Twins Meta Watcher."

        prompt = (
            soul_text + "\n\n---\n\n"
            f"INSPECT THESE TWIN OUTPUT SUMMARIES. Apply your rubric.\n\n"
            f"```\n{json.dumps(twin_summaries, indent=2, default=str)}\n```\n\n"
            f"Return STRICT JSON only, no markdown fences, no preamble. Schema:\n"
            f'{{"per_twin_verdicts": {{"<twin_name>": {{"verdict": '
            f'"healthy"|"stuck"|"stuck_legitimately"|"degraded"|"crashed", '
            f'"confidence": <int 0-100>, "evidence": "<one sentence>"}}}}, '
            f'"overall_meta_health": "all_healthy"|"some_degraded"|"watchers_failing", '
            f'"alarm_twins": [<twin names>], '
            f'"recommendation": "<one sentence>"}}'
        )

        started = time.time()
        try:
            proc = subprocess.run(
                ["copilot", "-p", prompt,
                 "--allow-all-tools", "--no-color",
                 "--no-custom-instructions", "--effort", "none"],
                cwd="/tmp", capture_output=True, text=True, timeout=120,
                env={**os.environ, "NO_COLOR": "1"},
            )
            raw = proc.stdout or ""
            lines = []
            for line in raw.splitlines():
                if line.strip().startswith(("Changes", "AI Credits", "Tokens")):
                    break
                lines.append(line)
            text = "\n".join(lines).strip()
            j_s = text.find("{"); j_e = text.rfind("}")
            if j_s < 0 or j_e <= j_s:
                llm_verdict = {"overall_meta_health": "unknown", "error": "no_json",
                               "raw": text[:300]}
            else:
                llm_verdict = json.loads(text[j_s:j_e+1])
        except subprocess.TimeoutExpired:
            llm_verdict = {"overall_meta_health": "unknown", "error": "timeout"}
        except Exception as e:
            llm_verdict = {"overall_meta_health": "unknown", "error": str(e)[:200]}

        report = {
            "twin": "TwinOfTwinsMetaWatcher",
            "frame_id": frame_id,
            "twins_inspected": [t["name"] for t in TWINS_TO_WATCH],
            "raw_per_twin_summaries": twin_summaries,
            "llm_elapsed_seconds": round(time.time() - started, 1),
            **llm_verdict,
        }
        (OUT_DIR / f"scan-{frame_id}.json").write_text(json.dumps(report, indent=2, default=str))
        return json.dumps(report, indent=2, default=str)


if __name__ == "__main__":
    print(TwinOfTwinsMetaWatcherAgent().perform(last_n=10))
