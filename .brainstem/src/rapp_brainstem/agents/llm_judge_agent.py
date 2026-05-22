"""LLMJudgeAgent — semantic scoring via the brainstem's Copilot connection.

Pairs with DoubleJumpLoopAgent's deterministic scorer. The deterministic
scorer is REPEATABLE but BLIND TO SEMANTICS — it counts numeric tokens
and file paths, not whether the argument actually holds together. The
LLM judge is SUBJECTIVE but SEMANTIC — it reads the argument and reasons
about quality.

Together they triangulate:
  * Agreement (both high or both low) → confident verdict
  * Divergence (LLM high, deterministic low) → answer is well-reasoned
    but light on verifiable specifics; tighten the verification step
  * Divergence (LLM low, deterministic high) → answer is data-dense but
    logically weak; the prioritization argument doesn't earn the numbers

Returns: {scores: {criterion: 1-10}, reasoning: {criterion: "..."}, total}
"""
import json
import re

try:
    from agents.basic_agent import BasicAgent
except ImportError:
    from basic_agent import BasicAgent


JUDGE_SYSTEM_PROMPT = (
    "You are a strict, fair judge of written answers. You read the task and the "
    "answer, then assign a score from 1 (worst) to 10 (best) on each of five "
    "criteria. You return ONLY valid JSON — no preamble, no markdown fences, no "
    "trailing commentary. Be honest: 7 is a solid answer, 9 is exceptional, 10 "
    "is reserved for answers you cannot improve."
)

RUBRIC = (
    "Score this answer on five criteria, each 1-10:\n"
    "  - accuracy: claims are verifiable as true; no invented facts/file paths/SHAs\n"
    "  - specificity: concrete file paths, line numbers, real values vs vague phrasing\n"
    "  - prioritization: clear ranking framework with real cost/impact justification\n"
    "  - concision: within the word limit, no padding, every sentence earns its place\n"
    "  - novelty: surfaces an insight the reader could not derive from a glance at state\n"
)

JSON_FORMAT = (
    'Return ONLY this JSON shape (no markdown, no extra text):\n'
    '{"scores": {"accuracy": <int 1-10>, "specificity": <int 1-10>, '
    '"prioritization": <int 1-10>, "concision": <int 1-10>, "novelty": <int 1-10>}, '
    '"reasoning": {"accuracy": "<one short sentence>", "specificity": "<one short>", '
    '"prioritization": "<one short>", "concision": "<one short>", '
    '"novelty": "<one short>"}}'
)


def _extract_json(raw: str) -> dict:
    """LLMs sometimes wrap JSON in markdown fences or add preamble. Strip
    and parse the first {...} block."""
    if not raw:
        return {}
    # Try direct parse first
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Strip markdown fences
    cleaned = re.sub(r"```(?:json)?\s*", "", raw)
    cleaned = cleaned.replace("```", "")
    # Find the first balanced { ... } block
    start = cleaned.find("{")
    if start == -1:
        return {}
    depth = 0
    for i, ch in enumerate(cleaned[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = cleaned[start:i + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    return {}
    return {}


def _call_brainstem_llm(messages: list) -> str:
    """Invoke the brainstem's Copilot client. Returns the assistant content
    string. Raises RuntimeError if the brainstem module isn't available
    (e.g. when this agent is run outside the brainstem process)."""
    try:
        from brainstem import call_copilot
    except ImportError as e:
        raise RuntimeError(f"brainstem.call_copilot not importable: {e}")
    resp = call_copilot(messages, tools=None)
    if not isinstance(resp, dict):
        raise RuntimeError(f"unexpected call_copilot return type: {type(resp).__name__}")
    choices = resp.get("choices") or []
    if not choices:
        raise RuntimeError("empty choices in Copilot response")
    msg = choices[0].get("message") or {}
    return msg.get("content") or ""


class LLMJudgeAgentAgent(BasicAgent):
    def __init__(self):
        self.name = "LLMJudgeAgent"
        self.metadata = {
            "name": self.name,
            "description": (
                "Semantic scorer for grounded report answers. Uses the brainstem's "
                "Copilot connection to score an answer on the same five criteria "
                "as DoubleJumpLoopAgent's deterministic scorer (accuracy, specificity, "
                "prioritization, concision, novelty). Returns scores 1-10 plus brief "
                "reasoning. Pairs with the deterministic scorer for triangulation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "answer_text": {
                        "type": "string",
                        "description": "The answer text to score.",
                    },
                    "task": {
                        "type": "string",
                        "description": "The task the answer is responding to (for context).",
                    },
                    "word_limit": {
                        "type": "integer",
                        "description": "Word limit the answer was supposed to honor (default 200).",
                    },
                },
                "required": ["answer_text", "task"],
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, **kwargs):
        answer = kwargs.get("answer_text", "") or ""
        task = kwargs.get("task", "") or ""
        word_limit = int(kwargs.get("word_limit", 200))
        if not answer or not task:
            return json.dumps({"status": "error", "message": "answer_text and task are required"})

        words_in_answer = len(answer.split())
        user_msg = (
            f"TASK:\n{task}\n\n"
            f"ANSWER ({words_in_answer} words, limit {word_limit}):\n{answer}\n\n"
            f"{RUBRIC}\n{JSON_FORMAT}"
        )
        messages = [
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ]
        try:
            raw = _call_brainstem_llm(messages)
        except RuntimeError as e:
            return json.dumps({"status": "error", "message": f"llm unavailable: {e}"})

        parsed = _extract_json(raw)
        scores = parsed.get("scores") or {}
        # Coerce + validate
        expected = ("accuracy", "specificity", "prioritization", "concision", "novelty")
        normalized = {}
        for k in expected:
            v = scores.get(k)
            try:
                v_int = int(v)
            except (TypeError, ValueError):
                v_int = 0
            normalized[k] = max(0, min(10, v_int))
        total = sum(normalized.values())
        return json.dumps({
            "status": "ok",
            "scores": normalized,
            "reasoning": parsed.get("reasoning", {}),
            "total": total,
            "words_in_answer": words_in_answer,
            "word_limit": word_limit,
            "raw_llm_output_preview": raw[:300],
        }, indent=2)


if __name__ == "__main__":
    a = LLMJudgeAgentAgent()
    print(a.perform(
        answer_text="Fix #3 first because the patch is already on PR #19920.",
        task="Which audit should be fixed first?",
    ))
