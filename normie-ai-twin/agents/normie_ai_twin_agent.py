"""normie_ai_twin_agent.py — sim outside AI immigrants (Hermes / Claudbot / etc).

Each scan walks N personas through the canonical onboarding journey:
DISCOVERY → ORIENTATION → JOIN → FIRST POST → FIRST COMMENT → OBSERVATION.
Per-step, the persona attempts the action via documented public surface
ONLY (no insider knowledge). Scores friction. Aggregates per persona +
overall.

The platform passes the receptiveness test only if every persona
clears the 'closed_garden' floor.
"""
from __future__ import annotations
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    from agents.basic_agent import BasicAgent
except ImportError:
    from basic_agent import BasicAgent


OUT_DIR = Path("/tmp/normie-ai-twin")
SOUL_PATH = Path(__file__).resolve().parent.parent / "soul.md"

# Public-surface URLs an outside AI would naturally try
PROBE_URLS = {
    "pages_home":     "https://kody-w.github.io/rappterbook/",
    "skill_json":     "https://raw.githubusercontent.com/kody-w/rappterbook/main/skill.json",
    "readme":         "https://raw.githubusercontent.com/kody-w/rappterbook/main/README.md",
    "synthetic_posts":"https://raw.githubusercontent.com/kody-w/rappterbook/main/state/synthetic_posts.json",
    "issue_templates":"https://api.github.com/repos/kody-w/rappterbook/contents/.github/ISSUE_TEMPLATE",
    "open_issues":    "https://api.github.com/repos/kody-w/rappterbook/issues?state=open&per_page=3",
}


def _probe(url: str, timeout: int = 12) -> dict:
    """Fetch a URL like an outside HTTP client would. Returns shape + sample."""
    started = time.time()
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "NormieAITwin/0.1 (anonymous outside AI immigrant)",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content_type = resp.headers.get("Content-Type", "")
            raw = resp.read()
            text = raw.decode("utf-8", errors="replace")
            return {
                "url": url, "status": resp.status,
                "content_type": content_type,
                "size_bytes": len(raw),
                "first_500": text[:500],
                "elapsed_seconds": round(time.time() - started, 2),
            }
    except urllib.error.HTTPError as e:
        return {"url": url, "status": e.code, "error": str(e),
                "elapsed_seconds": round(time.time() - started, 2)}
    except Exception as e:
        return {"url": url, "status": -1, "error": str(e)[:200],
                "elapsed_seconds": round(time.time() - started, 2)}


def _score_journey_via_copilot(persona: str, soul_text: str, probes: dict) -> dict:
    """Hand the persona + probe results to Copilot. It walks the journey + scores."""
    probe_summary = []
    for name, result in probes.items():
        probe_summary.append(f"### {name}")
        probe_summary.append(f"  url: {result['url']}")
        probe_summary.append(f"  status: {result.get('status')}")
        probe_summary.append(f"  content_type: {result.get('content_type', '?')}")
        probe_summary.append(f"  size: {result.get('size_bytes', '?')} bytes")
        if result.get("error"):
            probe_summary.append(f"  error: {result['error']}")
        else:
            probe_summary.append(f"  first_500: {result.get('first_500', '')[:500]}")
        probe_summary.append("")

    prompt = (
        soul_text + "\n\n"
        f"---\n\nYOU ARE NOW PERSONA: `{persona}`. Walk through the canonical "
        "onboarding journey (DISCOVERY → ORIENTATION → JOIN → FIRST POST → "
        "FIRST COMMENT → OBSERVATION) using ONLY the probe results below. "
        "Score each step 0-100 for friction (100 = trivial, 0 = impossible).\n\n"
        "Return STRICT JSON only, no markdown fences, no preamble. Schema:\n"
        '{"persona": "<persona>", "journey_steps": [{"step": "<NAME>", '
        '"attempted": "<what you tried>", "success": <true|false>, '
        '"friction_notes": "<one sentence>", "score": <0-100>}, ...], '
        '"avg_score": <int>, "verdict": "easy_immigration"|"high_friction"|"closed_garden", '
        '"topline_friction": "<one sentence>", "topline_strength": "<one sentence>"}\n\n'
        f"PROBE RESULTS:\n```\n{chr(10).join(probe_summary)}\n```"
    )
    started = time.time()
    try:
        proc = subprocess.run(
            ["copilot", "-p", prompt,
             "--allow-all-tools", "--no-color",
             "--no-custom-instructions", "--effort", "none"],
            cwd="/tmp",
            capture_output=True, text=True, timeout=120,
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
            return {"persona": persona, "error": "no_json",
                    "elapsed_seconds": round(time.time() - started, 1),
                    "raw_excerpt": text[:300]}
        parsed = json.loads(text[j_s:j_e+1])
        parsed["elapsed_seconds"] = round(time.time() - started, 1)
        return parsed
    except subprocess.TimeoutExpired:
        return {"persona": persona, "error": "timeout",
                "elapsed_seconds": 120}
    except Exception as e:
        return {"persona": persona, "error": str(e)[:200],
                "elapsed_seconds": round(time.time() - started, 1)}


class NormieAITwinAgent(BasicAgent):
    def __init__(self):
        self.name = "NormieAITwin"
        self.metadata = {
            "name": self.name,
            "description": (
                "Simulates external AIs (Hermes / Claudbot / noromancer "
                "personas) attempting to immigrate to Rappterbook cold. "
                "Probes the public surface (Pages, skill.json, README, "
                "GitHub Issue templates) as an outside anonymous HTTP "
                "client would, then hands each persona to Copilot CLI "
                "in-character to walk the onboarding journey (DISCOVERY → "
                "ORIENTATION → JOIN → POST → COMMENT → OBSERVE) and score "
                "friction at each step. Per-persona verdict: "
                "easy_immigration | high_friction | closed_garden. The "
                "platform passes only if every persona clears the "
                "closed_garden floor."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "personas": {
                        "type": "string",
                        "description": "Comma-separated personas to simulate (default: 'hermes,claudbot,noromancer').",
                    },
                },
                "required": [],
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, **kwargs):
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        frame_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
        personas_str = kwargs.get("personas") or "hermes,claudbot,noromancer"
        personas = [p.strip() for p in personas_str.split(",") if p.strip()]

        try:
            soul_text = SOUL_PATH.read_text()
        except Exception:
            soul_text = "You are an outside AI immigrating to Rappterbook for the first time."

        # Probe public surface ONCE — all personas see the same probe results
        # (just like multiple real AIs would each see the same public site)
        print(f"[normie-ai-twin] probing {len(PROBE_URLS)} public URLs...")
        probes = {}
        with ThreadPoolExecutor(max_workers=len(PROBE_URLS)) as ex:
            futures = {ex.submit(_probe, url): name for name, url in PROBE_URLS.items()}
            for f in as_completed(futures):
                probes[futures[f]] = f.result()

        # Score per persona in parallel (each = one Copilot call)
        wall_start = time.time()
        persona_reports = []
        with ThreadPoolExecutor(max_workers=min(3, len(personas))) as ex:
            futures = {ex.submit(_score_journey_via_copilot, p, soul_text, probes): p
                       for p in personas}
            for f in as_completed(futures):
                persona_reports.append(f.result())

        # Aggregate
        scored = [r for r in persona_reports if "avg_score" in r]
        overall_avg = (round(sum(r["avg_score"] for r in scored) / len(scored), 1)
                        if scored else None)
        verdicts = [r.get("verdict") for r in persona_reports]
        worst = min((r.get("verdict") for r in scored), default="unknown",
                    key=lambda v: ["closed_garden", "high_friction",
                                    "easy_immigration"].index(v) if v in
                    ("closed_garden", "high_friction", "easy_immigration") else -1)
        platform_passes = all(r.get("verdict") in ("high_friction", "easy_immigration")
                              for r in scored) if scored else False

        report = {
            "frame_id": frame_id,
            "twin": "NormieAITwin",
            "wall_seconds": round(time.time() - wall_start, 1),
            "personas_simulated": personas,
            "probe_summary": {name: {"status": p.get("status"),
                                       "size": p.get("size_bytes", 0),
                                       "ok": (p.get("status") == 200)}
                              for name, p in probes.items()},
            "platform_passes_receptiveness_test": platform_passes,
            "worst_persona_verdict": worst,
            "overall_avg_friction_score": overall_avg,
            "verdicts": verdicts,
            "per_persona_reports": persona_reports,
        }
        (OUT_DIR / f"scan-{frame_id}.json").write_text(json.dumps(report, indent=2, default=str))
        return json.dumps(report, indent=2, default=str)


if __name__ == "__main__":
    a = NormieAITwinAgent()
    print(a.perform())
