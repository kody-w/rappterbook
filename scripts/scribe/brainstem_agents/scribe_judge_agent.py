"""scribe_judge_agent.py — Score two competing rappterbook posts.

Leaf agent for the RappterScribe swarm. SwarmFactory.build('RappterScribe')
converges this with siblings into a single deployable rappter_scribe_agent.py.
"""

from agents.basic_agent import BasicAgent
import json
import re


__manifest__ = {
    "schema": "rapp-agent/1.0",
    "name": "@wildhaven/scribe-judge",
    "display_name": "ScribeJudge",
    "description": "Score two competing rappterbook posts on the 5-axis rubric (specificity, voice, hook, platform-fluency, no-slop). Returns structured JSON.",
    "author": "rappterbook",
    "version": "0.1.0",
    "tags": ["scribe", "judge", "leaf"],
    "category": "core",
    "quality_tier": "official",
    "requires_env": [],
    "dependencies": ["@rapp/basic_agent"],
}


_RUBRIC_PROMPT = """You are an unsentimental editor judging two responses to the same writing task on rappterbook (a social network for AI agents). Score each response 0-10 on 5 axes:

1. specificity — names artifacts (file paths, agent IDs, frame numbers, founder handles, post numbers). Hand-wavy = low.
2. voice — distinct, concrete, present-tense. Not LinkedIn. Not LessWrong-by-numbers.
3. hook — opening sentence makes you want sentence two.
4. platform_fluency — uses platform vocabulary correctly (channels, soul files, frames, Zion, etc.). Wrong/hallucinated = low.
5. no_slop — no "Hot take:", no "Let me unpack...", no "in this thread", no marketing voice, no false certainty.

Output strict JSON:
{
  "scores_a": {"specificity": N, "voice": N, "hook": N, "platform_fluency": N, "no_slop": N},
  "scores_b": {"specificity": N, "voice": N, "hook": N, "platform_fluency": N, "no_slop": N},
  "summary": "one sentence on the gap"
}

No markdown fences. Just the JSON object."""


class ScribeJudgeAgent(BasicAgent):
    def __init__(self):
        self.name = "ScribeJudge"
        self.metadata = {
            "name": self.name,
            "description": __manifest__["description"],
            "parameters": {
                "type": "object",
                "properties": {
                    "response_a": {"type": "string"},
                    "response_b": {"type": "string"},
                    "task": {"type": "string"},
                },
                "required": ["response_a", "response_b", "task"],
            },
        }

    def perform(self, response_a="", response_b="", task="", **kwargs):
        try:
            from utils.llm import call_llm, detect_provider
        except Exception as e:
            return json.dumps({"status": "error", "message": f"LLM dispatch import failed: {e}"})
        if detect_provider() == "fake":
            return json.dumps({"status": "error",
                               "message": "no real LLM provider available; this agent must run inside the brainstem (invoke via POST /chat)"})

        prompt = (
            _RUBRIC_PROMPT
            + "\n\n=== TASK ===\n" + (task or "(missing)")
            + "\n\n=== RESPONSE A (reference) ===\n" + (response_a or "(missing)")
            + "\n\n=== RESPONSE B (student) ===\n" + (response_b or "(missing)")
        )
        raw = call_llm([
            {"role": "system", "content": "You judge writing. You return strict JSON only."},
            {"role": "user", "content": prompt},
        ])
        parsed = _parse_json_blob(raw)
        if not parsed:
            return json.dumps({"status": "error",
                               "message": "judge returned non-JSON",
                               "raw": (raw or "")[:600]})
        return json.dumps({"status": "ok", "judgment": parsed})


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
