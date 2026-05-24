"""mutation_efficacy_twin_agent.py — systems-reviewer for infinite-doublejump.

Reads the last N rounds of the doublejump chronicle + the state file,
hands the time-series to Copilot CLI in 'harsh systems analyst' persona,
verdicts evolving | stalled | thrashing | insufficient_data.

Catches the failure mode where mutations fire but nothing moves.
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


REPO = Path("/Users/kodyw/Documents/GitHub/Rappter/rappterbook")
CHRONICLE_DIR = REPO / "docs/chronicles/doublejump"
STATE_PATH = REPO / "docs/chronicles/infinite_doublejump_state.json"
OUT_DIR = Path("/tmp/mutation-efficacy-twin")
SOUL_PATH = Path(__file__).resolve().parent.parent / "soul.md"


def _load_chronicle(last_n: int = 30) -> list:
    if not CHRONICLE_DIR.exists():
        return []
    files = sorted(CHRONICLE_DIR.glob("round-*.json"))[-last_n:]
    out = []
    for f in files:
        try:
            out.append(json.loads(f.read_text()))
        except Exception:
            continue
    return out


def _load_state() -> dict:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:
        return {}


def _summarize_for_llm(records: list, state: dict) -> str:
    """Compact text dossier — what the systems-analyst would see."""
    if not records:
        return "NO_CHRONICLE_DATA"
    lines = []
    lines.append(f"# Doublejump chronicle: last {len(records)} rounds")
    lines.append(f"state.round_number = {state.get('round_number')}")
    lines.append(f"state.total_mutations = {len(state.get('mutations', []))}")
    lines.append(f"state.max_swarm_num = {state.get('max_swarm_num')}")
    lines.append(f"state.quarantined_total = {len(state.get('quarantined_suffixes', []))}")
    lines.append("")
    lines.append("## per-round trajectory:")
    for r in records:
        cons = r.get("consensus") or {}
        mut = r.get("mutation") or {}
        lines.append(
            f"r{r.get('round_number'):>3}  "
            f"median={cons.get('median')}  "
            f"stdev={cons.get('stdev')}  "
            f"verdict_mode={cons.get('verdict_mode')}  "
            f"outliers={len(cons.get('outliers') or [])}  "
            f"swarm_size={r.get('twins_swarm_size')}  "
            f"mutation={mut.get('kind')}"
        )
    lines.append("")
    lines.append("## mutation log (most recent 15):")
    for m in (state.get("mutations") or [])[-15:]:
        if m.get("kind") == "quarantine_and_rehatch":
            lines.append(f"  quarantine: {m.get('old_suffix')} (avg {m.get('old_score')}, "
                         f"Δ{m.get('old_delta_from_median')}) → {m.get('new_suffix')}")
        elif m.get("kind") == "soft_soul_curate":
            lines.append(f"  curate:     {m.get('twin_suffix')} (Δ{m.get('delta_from_median')})")
        else:
            lines.append(f"  {m.get('kind')}")
    return "\n".join(lines)


class MutationEfficacyTwinAgent(BasicAgent):
    def __init__(self):
        self.name = "MutationEfficacyTwin"
        self.metadata = {
            "name": self.name,
            "description": (
                "Reads the last N rounds of the infinite-doublejump chronicle "
                "and judges whether the loop is genuinely evolving, stalled, "
                "or thrashing. Catches the failure mode where mutations fire "
                "constantly but downstream metrics don't move. Returns "
                "structured JSON: verdict + confidence + evidence + "
                "trajectory_summary + recommendation + key_metrics."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "last_n": {
                        "type": "integer",
                        "description": "How many recent rounds to analyze (default 30).",
                    },
                },
                "required": [],
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, **kwargs):
        last_n = int(kwargs.get("last_n", 30))
        last_n = max(5, min(last_n, 100))
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        frame_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")

        records = _load_chronicle(last_n)
        state = _load_state()
        if len(records) < 5:
            return json.dumps({
                "status": "insufficient_data", "frame_id": frame_id,
                "rounds_available": len(records),
                "verdict": "insufficient_data",
                "advisory": f"need ≥5 rounds; found {len(records)}",
            })

        # Compute deterministic key_metrics ourselves (LLM can be sloppy on math)
        def _med(rs):
            vals = [(r.get("consensus") or {}).get("median") for r in rs]
            vals = [v for v in vals if isinstance(v, (int, float))]
            return round(sum(vals) / len(vals), 2) if vals else None
        def _stdev(rs):
            vals = [(r.get("consensus") or {}).get("stdev") for r in rs]
            vals = [v for v in vals if isinstance(v, (int, float))]
            return round(sum(vals) / len(vals), 2) if vals else None
        half = max(1, len(records) // 2)
        first_half, second_half = records[:half], records[half:]
        muts_first = sum(1 for r in first_half
                         if (r.get("mutation") or {}).get("kind", "").startswith(("quarantine", "soft_soul")))
        muts_second = sum(1 for r in second_half
                          if (r.get("mutation") or {}).get("kind", "").startswith(("quarantine", "soft_soul")))
        key_metrics = {
            "rounds_analyzed": len(records),
            "median_first_half_avg": _med(first_half),
            "median_second_half_avg": _med(second_half),
            "median_delta": (_med(second_half) - _med(first_half))
                            if (_med(second_half) and _med(first_half)) else None,
            "stdev_first_half_avg": _stdev(first_half),
            "stdev_second_half_avg": _stdev(second_half),
            "mutations_first_half": muts_first,
            "mutations_second_half": muts_second,
            "mutations_per_round_first_half": round(muts_first / max(len(first_half), 1), 2),
            "mutations_per_round_second_half": round(muts_second / max(len(second_half), 1), 2),
        }

        # Send to Copilot for the verdict
        try:
            soul_text = SOUL_PATH.read_text()
        except Exception:
            soul_text = "You are the Mutation Efficacy Twin. Judge whether the doublejump loop is evolving, stalled, or thrashing."

        dossier = _summarize_for_llm(records, state)
        prompt = (
            soul_text + "\n\n---\n\n"
            f"COMPUTED KEY METRICS (already calculated, use these as ground truth):\n"
            f"{json.dumps(key_metrics, indent=2)}\n\n"
            f"DOSSIER:\n```\n{dossier}\n```\n\n"
            f"Now apply your rubric. Return STRICT JSON, no markdown fences, no preamble. Schema:\n"
            f'{{"verdict": "evolving"|"stalled"|"thrashing"|"insufficient_data", '
            f'"confidence": <int 0-100>, "evidence": [<3-6 short bullet strings>], '
            f'"trajectory_summary": "<one sentence>", "recommendation": "<one sentence>"}}'
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
                llm_verdict = {"verdict": "unknown", "error": "no_json",
                               "raw": text[:300]}
            else:
                llm_verdict = json.loads(text[j_s:j_e+1])
        except subprocess.TimeoutExpired:
            llm_verdict = {"verdict": "unknown", "error": "timeout"}
        except Exception as e:
            llm_verdict = {"verdict": "unknown", "error": str(e)[:200]}

        report = {
            "twin": "MutationEfficacyTwin",
            "frame_id": frame_id,
            "rounds_analyzed": len(records),
            "round_range": [records[0].get("round_number"), records[-1].get("round_number")],
            "key_metrics": key_metrics,
            "llm_elapsed_seconds": round(time.time() - started, 1),
            **llm_verdict,
        }
        (OUT_DIR / f"scan-{frame_id}.json").write_text(json.dumps(report, indent=2, default=str))
        return json.dumps(report, indent=2, default=str)


if __name__ == "__main__":
    print(MutationEfficacyTwinAgent().perform(last_n=30))
