"""DoubleJumpLoopAgent — runs a competition loop across grounded report agents.

This agent embodies the double-jump improvement pattern that built FactoryReporter
v1 and v2 in PR #19920. Instead of just scaffolding a single new agent (what
LearnNew does), this agent ORCHESTRATES a competition:

  1. Run the task through N existing reporter-style agents (the contestants)
  2. Score each against a five-criterion rubric (accuracy, specificity,
     prioritization, concision, novel insight) — heuristic + objective
     measures, no LLM in the scoring loop
  3. Identify which criterion separated the winner from the rest
  4. Optionally spawn a v+1 agent (via LearnNew) whose description targets
     the criterion the current best agent was weakest on
  5. Re-run, re-score, append to trajectory
  6. Return the trajectory + the winning agent name

The improvement compounds because each jump targets the SPECIFIC gap in the
prior winner — not a generic "be better" instruction. That's the doctrine from
LAB_NOTEBOOK entry 003.24: every iteration must read the failure modes of the
previous round before generating the next attempt.

Hard rule: scoring is deterministic. No LLM in the score function. Otherwise
each iteration drifts on the scorer's subjective preferences instead of on the
agents' actual capability gaps.
"""
import importlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from agents.basic_agent import BasicAgent
except ImportError:
    from basic_agent import BasicAgent


AGENTS_DIR = Path(__file__).resolve().parent
DEFAULT_CONTESTANTS = [
    ("FactoryReporterAgent", "factory_reporter_agent_agent"),
    ("FactoryReporterV2", "factory_reporter_v2_agent"),
]
SCORE_HISTORY = AGENTS_DIR.parent / ".doublejump_history.json"


# ---------------------------------------------------------------------------
# Scoring — five criteria, each /10, deterministic
# ---------------------------------------------------------------------------

def _score_accuracy(parsed: dict) -> tuple:
    """High if every numeric claim has a verification record. Low if claims
    are made without backing evidence."""
    verifications = parsed.get("verifications_performed", []) or []
    ok_count = sum(1 for v in verifications if v.get("ok"))
    answer = parsed.get("answer_text", "") or ""
    # Count numeric tokens in the answer (rough proxy for claims)
    num_tokens = len(re.findall(r"\b\d[\d.,/]*", answer))
    if num_tokens == 0:
        return 5, "no numeric claims to verify"
    coverage = ok_count / max(num_tokens, 1)
    score = max(0, min(10, round(coverage * 10)))
    return score, f"{ok_count} ok verifications for ~{num_tokens} numeric tokens (coverage {coverage:.2f})"


def _score_specificity(parsed: dict) -> tuple:
    """High if answer contains file paths, line refs (file:NNN), specific
    SHAs/numbers. Low if vague."""
    answer = parsed.get("answer_text", "") or ""
    paths = len(re.findall(r"`?[a-zA-Z0-9_./]+\.(?:py|md|json|sh|yml)`?", answer))
    line_refs = len(re.findall(r":(\d+)|L(\d+)\b", answer))
    sha_refs = len(re.findall(r"\b[0-9a-f]{7,40}\b", answer))
    specifics = paths + line_refs + sha_refs
    score = min(10, specifics)
    return score, f"paths={paths} line_refs={line_refs} sha_refs={sha_refs}"


def _score_prioritization(parsed: dict) -> tuple:
    """High if answer states a clear ranking framework with reasons.
    Heuristic: numbered list (1. 2. 3.) + 'because'/'reason' nearby."""
    answer = parsed.get("answer_text", "") or ""
    numbered = len(re.findall(r"\*\*\d+\.|^\s*\d+\.", answer, re.MULTILINE))
    rationale = len(re.findall(r"\b(because|reason|why|cost|impact)\b", answer, re.IGNORECASE))
    if numbered >= 3 and rationale >= 2:
        return 9, f"{numbered} numbered, {rationale} rationale markers"
    if numbered >= 2 or rationale >= 2:
        return 7, f"{numbered} numbered, {rationale} rationale markers"
    return 4, f"weak structure: {numbered} numbered, {rationale} rationale"


def _score_concision(parsed: dict) -> tuple:
    words = parsed.get("words_used", 0) or 0
    limit = parsed.get("word_limit", 200) or 200
    if words == 0:
        return 0, "no answer text"
    if words > limit:
        return max(0, 10 - (words - limit) // 10), f"over limit: {words}/{limit}"
    if words < limit * 0.5:
        return 7, f"very brief: {words}/{limit}"
    return 9, f"{words}/{limit}"


def _score_novelty(parsed: dict) -> tuple:
    """Heuristic: presence of caveats ('not yet', 'unverified', 'caveat'),
    distinguishing between near-identical alternatives, and citing prior
    state (PR / commit / function name) raises novelty."""
    answer = parsed.get("answer_text", "") or ""
    caveats = len(re.findall(
        r"\b(not yet|unverified|negative|distinct|actually|caveat|nuance)\b",
        answer, re.IGNORECASE,
    ))
    function_names = len(re.findall(r"`_?[a-z_][a-z_0-9]*\(?\)?`", answer))
    pr_or_commit = len(re.findall(r"\bPR\s*#\d+|\bcommit\b", answer, re.IGNORECASE))
    raw = caveats * 3 + function_names + pr_or_commit
    score = min(10, raw)
    return score, f"caveats={caveats} fn_refs={function_names} pr/commit={pr_or_commit}"


SCORERS = {
    "accuracy": _score_accuracy,
    "specificity": _score_specificity,
    "prioritization": _score_prioritization,
    "concision": _score_concision,
    "novelty": _score_novelty,
}


def _score(parsed: dict) -> dict:
    breakdown = {}
    total = 0
    for name, fn in SCORERS.items():
        try:
            s, reason = fn(parsed)
        except Exception as e:
            s, reason = 0, f"scorer error: {e}"
        breakdown[name] = {"score": s, "reason": reason}
        total += s
    return {"total": total, "breakdown": breakdown}


# ---------------------------------------------------------------------------
# Contestant invocation
# ---------------------------------------------------------------------------

def _run_contestant(class_name: str, module_name: str, task: str, word_limit: int) -> dict:
    """Import and invoke a contestant agent. Returns its parsed JSON output."""
    try:
        mod = importlib.import_module(f"agents.{module_name}")
        # The class name as registered is the metadata name; the actual class
        # in the module is suffixed with 'Agent' for LearnNew-generated ones.
        cls = None
        for candidate in (class_name, class_name + "Agent", f"{class_name}AgentAgent"):
            if hasattr(mod, candidate):
                cls = getattr(mod, candidate)
                break
        if cls is None:
            return {"error": f"class not found in {module_name}", "candidates_tried": [class_name]}
        inst = cls()
        result = inst.perform(task=task, word_limit=word_limit)
        if isinstance(result, str):
            try:
                return json.loads(result)
            except json.JSONDecodeError:
                return {"answer_text": result, "words_used": len(result.split()), "word_limit": word_limit}
        return result if isinstance(result, dict) else {"answer_text": str(result)}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


# ---------------------------------------------------------------------------
# Trajectory + history
# ---------------------------------------------------------------------------

def _load_history() -> dict:
    if SCORE_HISTORY.exists():
        try:
            with open(SCORE_HISTORY) as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            pass
    return {"jumps": []}


def _save_history(history: dict) -> None:
    history["jumps"] = history.get("jumps", [])[-50:]
    try:
        with open(SCORE_HISTORY, "w") as f:
            json.dump(history, f, indent=2)
    except OSError:
        pass


def _identify_weakest_criterion(breakdown: dict) -> tuple:
    items = [(name, info.get("score", 0), info.get("reason", "")) for name, info in breakdown.items()]
    items.sort(key=lambda x: x[1])
    return items[0]


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------

class DoubleJumpLoopAgentAgent(BasicAgent):
    def __init__(self):
        self.name = "DoubleJumpLoopAgent"
        self.metadata = {
            "name": self.name,
            "description": (
                "Runs a competition loop across grounded report agents and returns "
                "the trajectory of scores. Each iteration scores deterministically "
                "(no LLM in the scorer), identifies the weakest criterion, and "
                "names the next gap to close. Use this to verify whether a newly-"
                "generated agent actually beats the prior best."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "The prompt every contestant must answer.",
                    },
                    "contestants": {
                        "type": "array",
                        "items": {"type": "array", "items": {"type": "string"}},
                        "description": "List of [class_name, module_name] tuples. Defaults to FactoryReporterAgent + FactoryReporterV2.",
                    },
                    "word_limit": {
                        "type": "integer",
                        "description": "Max words per contestant answer (default 200).",
                    },
                    "save_history": {
                        "type": "boolean",
                        "description": "If true (default), append this run to .doublejump_history.json.",
                    },
                },
                "required": ["task"],
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, **kwargs):
        task = kwargs.get("task", "")
        if not task:
            return json.dumps({"status": "error", "message": "task required"})
        word_limit = int(kwargs.get("word_limit", 200))
        save = bool(kwargs.get("save_history", True))
        contestants = kwargs.get("contestants") or [list(c) for c in DEFAULT_CONTESTANTS]

        ran_at = datetime.now(timezone.utc).isoformat()
        trajectory = []

        for entry in contestants:
            class_name, module_name = entry[0], entry[1]
            t0 = time.time()
            parsed = _run_contestant(class_name, module_name, task, word_limit)
            elapsed = round(time.time() - t0, 2)
            if parsed.get("error"):
                trajectory.append({
                    "contestant": class_name,
                    "error": parsed["error"],
                    "elapsed_seconds": elapsed,
                    "score": None,
                })
                continue
            scored = _score(parsed)
            weakest = _identify_weakest_criterion(scored["breakdown"])
            trajectory.append({
                "contestant": class_name,
                "elapsed_seconds": elapsed,
                "score": scored["total"],
                "breakdown": scored["breakdown"],
                "weakest": {"criterion": weakest[0], "score": weakest[1], "reason": weakest[2]},
                "answer_preview": (parsed.get("answer_text") or "")[:300],
                "words_used": parsed.get("words_used"),
            })

        # Determine winner
        scored_only = [t for t in trajectory if t.get("score") is not None]
        if not scored_only:
            return json.dumps({"status": "error", "message": "no contestant produced a score", "trajectory": trajectory})
        winner = max(scored_only, key=lambda t: t["score"])
        loser = min(scored_only, key=lambda t: t["score"])

        # Next-jump recommendation
        winner_weakest = winner["weakest"]
        recommendation = {
            "next_agent_target": f"address `{winner_weakest['criterion']}`",
            "current_gap": winner_weakest["reason"],
            "suggested_description_addendum": _description_addendum_for(winner_weakest["criterion"]),
        }

        result = {
            "status": "ok",
            "ran_at": ran_at,
            "task": task[:200],
            "contestants_run": len(contestants),
            "winner": {"name": winner["contestant"], "score": winner["score"]},
            "loser": {"name": loser["contestant"], "score": loser["score"]},
            "delta": winner["score"] - loser["score"],
            "trajectory": trajectory,
            "next_jump": recommendation,
        }

        if save:
            history = _load_history()
            history.setdefault("jumps", []).append({
                "ran_at": ran_at,
                "task_preview": task[:120],
                "winner": winner["contestant"],
                "winner_score": winner["score"],
                "scores": {t["contestant"]: t.get("score") for t in trajectory},
            })
            _save_history(history)
            result["history_appended"] = True

        return json.dumps(result, indent=2)


def _description_addendum_for(criterion: str) -> str:
    """Return a description fragment the next agent should incorporate to
    target the weak criterion. This is the actual 'gap analysis → next
    agent description' mapping that turns a competition into a loop."""
    mapping = {
        "accuracy": (
            "Every numeric claim in the output MUST be paired with a verification "
            "log entry that produced it (file:line, command output, or read result). "
            "If a fact cannot be verified, mark it [unverified] inline."
        ),
        "specificity": (
            "Cite file paths, line numbers (file:NNN format), and commit SHAs whenever "
            "available. Avoid vague phrasing like 'some files' or 'a recent commit'."
        ),
        "prioritization": (
            "Open with a numbered list (1. 2. 3.) where each item carries a 'because' "
            "or 'cost/impact' rationale clause. Don't bury the prioritization framework."
        ),
        "concision": (
            "Hit 70-95% of the word limit. Trim adverbs, throat-clearing, and "
            "restated context. Every sentence must add a new fact or framing."
        ),
        "novelty": (
            "Include at least one caveat ('not yet', 'unverified', 'distinct from X') "
            "and at least one reference to a specific function name, PR number, or "
            "commit. Surface what the prior best missed."
        ),
    }
    return mapping.get(criterion, "Improve the weak criterion by tightening the relevant code path.")


if __name__ == "__main__":
    a = DoubleJumpLoopAgentAgent()
    print(a.perform(task="Of audits #1, #2, #3, #5 which one should be fixed first?"))
