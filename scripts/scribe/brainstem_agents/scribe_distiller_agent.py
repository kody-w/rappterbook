"""scribe_distiller_agent.py — Distill 2-3 actionable style rules from a judge gap.

Leaf agent for the RappterScribe swarm.
"""

from agents.basic_agent import BasicAgent
import json
import re


__manifest__ = {
    "schema": "rapp-agent/1.0",
    "name": "@wildhaven/scribe-distiller",
    "display_name": "ScribeDistiller",
    "description": "Distill 2-3 concrete style rules from a judge's gap report. Rules are imperative, artifact-grounded, and replace older vague rules.",
    "author": "rappterbook",
    "version": "0.1.0",
    "tags": ["scribe", "distiller", "leaf"],
    "category": "core",
    "quality_tier": "official",
    "requires_env": [],
    "dependencies": ["@rapp/basic_agent"],
}


_DISTILLER_PROMPT = """You are tuning a writing student's instructions. The student lost (or tied) to a reference on a rappterbook post task. Your job: turn the gap into 2-3 imperative, concrete rules the student must apply next time.

Constraints:
- Each rule MUST be actionable in one sentence.
- NEVER write "be specific" / "be concrete" / "try to". Rules name an artifact class (file path, frame number, founder handle, channel slug, commit SHA, post number) or a structural move (open with the most concrete noun; cut the topic sentence).
- If a current rule is now obsolete or redundant, list it under `obsoleted` so it gets dropped.
- Maximum 3 new rules. Fewer is better.

Output strict JSON:
{
  "new_rules": ["rule one", "rule two"],
  "obsoleted": ["substring of any current rule that's now redundant"]
}

No markdown fences. Just the JSON object."""


class ScribeDistillerAgent(BasicAgent):
    def __init__(self):
        self.name = "ScribeDistiller"
        self.metadata = {
            "name": self.name,
            "description": __manifest__["description"],
            "parameters": {
                "type": "object",
                "properties": {
                    "judgment": {"type": "object"},
                    "response_a": {"type": "string"},
                    "response_b": {"type": "string"},
                    "task": {"type": "string"},
                    "current_rules": {"type": "array"},
                },
                "required": ["judgment", "response_a", "response_b"],
            },
        }

    def perform(self, judgment=None, response_a="", response_b="",
                task="", current_rules=None, **kwargs):
        try:
            from utils.llm import call_llm, detect_provider
        except Exception as e:
            return json.dumps({"status": "error", "message": f"LLM dispatch import failed: {e}"})
        if detect_provider() == "fake":
            return json.dumps({"status": "error",
                               "message": "no real LLM provider; invoke via POST /chat"})

        judgment = judgment or {}
        current_rules = current_rules or []
        prompt = (
            _DISTILLER_PROMPT
            + "\n\n=== JUDGMENT ===\n" + json.dumps(judgment, indent=2)
            + "\n\n=== TASK ===\n" + (task or "(missing)")
            + "\n\n=== REFERENCE (winner) ===\n" + (response_a or "(missing)")
            + "\n\n=== STUDENT (loser/tie) ===\n" + (response_b or "(missing)")
            + "\n\n=== CURRENT STUDENT RULES (do not duplicate) ===\n"
            + ("\n".join(f"- {r}" for r in current_rules) if current_rules else "(none yet)")
        )
        raw = call_llm([
            {"role": "system", "content": "You produce concrete imperative rules in JSON. Never prose."},
            {"role": "user", "content": prompt},
        ])
        parsed = _parse_json_blob(raw)
        if not parsed:
            return json.dumps({"status": "error",
                               "message": "distiller returned non-JSON",
                               "raw": (raw or "")[:600]})
        new_rules = [r for r in (parsed.get("new_rules") or [])
                     if isinstance(r, str) and len(r.split()) >= 8]
        obsoleted = [s for s in (parsed.get("obsoleted") or []) if isinstance(s, str)]
        return json.dumps({"status": "ok", "new_rules": new_rules, "obsoleted": obsoleted})


def _parse_json_blob(raw: str) -> dict:
    if not raw:
        return {}
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    m = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {}
