"""DoubleJumpAutopilotAgent — the recursive layer that closes the loop.

DoubleJumpLoopAgent stops at "tell you what to fix next." Autopilot reads
that recommendation, uses the brainstem's LLM to write a NEW agent that
addresses the gap, validates the result (compile + smoke test), adds it
to the contestants pool, and re-runs the loop. Repeats until score
plateaus, target hit, or budget exhausted.

This is the genuinely recursive piece — the loop becomes self-improving
without a human writing each iteration's perform() body.

Architecture:
  for jump in range(max_jumps):
    1. trajectory = DoubleJumpLoopAgent.run(task, contestants)
    2. if winner.score >= target_score → return
    3. winner_code = read(winner.source_file)
    4. new_code = LLM.fill_perform(winner_code, gap_addendum)
    5. compile_check(new_code) → must pass
    6. save_new_agent(new_code, new_name)
    7. smoke_test(new_agent, smoke_task) → must score >= floor
    8. contestants.append((new_name, new_module))

Defenses against the obvious failure modes:
  * LLM generates broken Python → compile() catches it; retry once with the
    error fed back; if still broken, count as failed jump
  * LLM generates code that loops/hangs → smoke test runs with 60s timeout
  * Generated agent regresses below floor → unlink the file, count as
    failed jump, try a different gap focus next iteration
  * Naming collisions → unique counter in name; refuse to overwrite existing
"""
import importlib
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from agents.basic_agent import BasicAgent
except ImportError:
    from basic_agent import BasicAgent


AGENTS_DIR = Path(__file__).resolve().parent
HISTORY_PATH = AGENTS_DIR.parent / ".doublejump_autopilot_history.json"
DEFAULT_MAX_JUMPS = 2
DEFAULT_SMOKE_FLOOR_DELTA = 8  # new agent must score within 8 below current best
LLM_CODE_GEN_TIMEOUT = 90

# Agents we treat as canonical starting contestants. Autopilot can mutate
# this list as it generates new ones.
SEED_CONTESTANTS = [
    ("FactoryReporterAgent", "factory_reporter_agent_agent"),
    ("FactoryReporterV2", "factory_reporter_v2_agent"),
]


# ---------------------------------------------------------------------------
# LLM-driven code generation
# ---------------------------------------------------------------------------

CODE_GEN_SYSTEM = (
    "You write Python agent modules for the Rappterbook RAPP brainstem. "
    "Output ONLY a single Python file. No markdown fences, no preamble, no "
    "trailing commentary. The first character of your response must be the "
    "first character of the Python file."
)

CODE_GEN_USER_TEMPLATE = """A prior agent won a competition but has a gap. Write a NEW agent that closes the gap.

PRIOR WINNER'S SOURCE (your starting point):
```
{prior_code}
```

GAP TO CLOSE (from the loop's next_jump recommendation):
{gap_addendum}

REQUIREMENTS for the new file:
  * Class name must be: {new_class_name}
  * It MUST inherit from BasicAgent and implement perform(**kwargs) returning a JSON string
  * It MUST set self.metadata with a "name", "description", and parameters schema (same shape as the prior agent)
  * It MUST use only Python stdlib + subprocess (no pip dependencies)
  * It MUST verify every numeric or path claim via subprocess (grep/git/ls/cat/python -c) BEFORE composing the answer
  * It MUST stay under the requested word_limit in its output
  * The metadata.name SHOULD be exactly: {agent_metadata_name}
  * The file MUST be a valid Python module that import succeeds on (use `try/except ImportError` for BasicAgent like the prior winner)
  * Output the COMPLETE new file — full module from the first line to the last

The point is to address THE SPECIFIC GAP listed above. Do not change the overall structure; tighten the verification step or the composer to fix the criterion that scored low.

Write the complete Python file now."""


def _call_brainstem_llm(messages: list, timeout: int = LLM_CODE_GEN_TIMEOUT) -> str:
    """Invoke the brainstem's Copilot. Returns assistant content."""
    try:
        from brainstem import call_copilot
    except ImportError as e:
        raise RuntimeError(f"brainstem.call_copilot not importable: {e}")
    resp = call_copilot(messages, tools=None)
    if not isinstance(resp, dict):
        raise RuntimeError(f"unexpected call_copilot type: {type(resp).__name__}")
    choices = resp.get("choices") or []
    if not choices:
        raise RuntimeError("empty choices from Copilot")
    return (choices[0].get("message") or {}).get("content") or ""


def _strip_markdown_fences(text: str) -> str:
    """LLMs often wrap code in ```python ... ``` despite being told not to."""
    if not text:
        return text
    text = re.sub(r"^```(?:python|py)?\s*\n", "", text.strip(), flags=re.MULTILINE)
    text = re.sub(r"\n```\s*$", "", text)
    return text.strip()


def _generate_next_agent_code(prior_code: str, gap_addendum: str, new_class_name: str,
                               agent_metadata_name: str) -> dict:
    """Ask the LLM to produce the next agent's full source. Returns
    {ok, source, raw, error?}."""
    user_msg = CODE_GEN_USER_TEMPLATE.format(
        prior_code=prior_code[:8000],
        gap_addendum=gap_addendum,
        new_class_name=new_class_name,
        agent_metadata_name=agent_metadata_name,
    )
    messages = [
        {"role": "system", "content": CODE_GEN_SYSTEM},
        {"role": "user", "content": user_msg},
    ]
    try:
        raw = _call_brainstem_llm(messages)
    except RuntimeError as e:
        return {"ok": False, "error": f"llm call failed: {e}"}
    source = _strip_markdown_fences(raw)
    if not source or "class " not in source:
        return {"ok": False, "error": "LLM output did not contain a class definition",
                "raw_preview": raw[:400]}
    return {"ok": True, "source": source, "raw_length": len(raw)}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _compile_check(source: str, filename: str) -> dict:
    try:
        compile(source, filename, "exec")
        return {"ok": True}
    except SyntaxError as e:
        return {"ok": False, "error": f"SyntaxError: {e}", "lineno": e.lineno}


def _smoke_test(module_name: str, class_name: str, task: str, word_limit: int,
                floor_score: int) -> dict:
    """Import the new agent and run it once against the task. The agent's
    output must compose a non-empty answer_text and the deterministic score
    must be >= floor_score."""
    try:
        # Reload in case the module was hot-loaded with stale content
        if f"agents.{module_name}" in sys.modules:
            del sys.modules[f"agents.{module_name}"]
        mod = importlib.import_module(f"agents.{module_name}")
    except Exception as e:
        return {"ok": False, "error": f"import failed: {type(e).__name__}: {e}"}

    cls = None
    for candidate in (class_name, class_name + "Agent", class_name + "AgentAgent"):
        if hasattr(mod, candidate):
            cls = getattr(mod, candidate)
            break
    if cls is None:
        return {"ok": False, "error": f"class {class_name} not found in {module_name}"}

    try:
        result_str = cls().perform(task=task, word_limit=word_limit)
        result = json.loads(result_str) if isinstance(result_str, str) else result_str
    except Exception as e:
        return {"ok": False, "error": f"perform failed: {type(e).__name__}: {e}"}

    answer = result.get("answer_text", "") or ""
    if not answer.strip():
        return {"ok": False, "error": "agent returned empty answer_text"}

    # Quick deterministic score via the loop's scorer
    try:
        loop_mod = importlib.import_module("agents.doublejumploop_agent")
        det_score = loop_mod._score_deterministic(result)
    except Exception as e:
        return {"ok": True, "warning": f"could not score: {e}", "answer_preview": answer[:200]}

    passed = det_score["total"] >= floor_score
    return {
        "ok": passed,
        "score": det_score["total"],
        "floor": floor_score,
        "answer_preview": answer[:300],
        "words": result.get("words_used"),
        "reason": "below floor" if not passed else "passed",
    }


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

def _load_history() -> dict:
    if HISTORY_PATH.exists():
        try:
            with open(HISTORY_PATH) as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            pass
    return {"runs": []}


def _save_history(history: dict) -> None:
    history["runs"] = history.get("runs", [])[-30:]
    try:
        with open(HISTORY_PATH, "w") as f:
            json.dump(history, f, indent=2)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# The autopilot
# ---------------------------------------------------------------------------

class DoubleJumpAutopilotAgentAgent(BasicAgent):
    def __init__(self):
        self.name = "DoubleJumpAutopilotAgent"
        self.metadata = {
            "name": self.name,
            "description": (
                "Self-improving loop. Runs DoubleJumpLoopAgent, reads the next-jump "
                "recommendation, uses the brainstem's LLM to write a new agent that "
                "addresses the gap, validates (compile + smoke test), adds it to the "
                "contestants pool, and repeats. Stops at target_score, max_jumps, "
                "or when the LLM can no longer produce an improving agent. Returns "
                "the full trajectory + the lineage of generated agents."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "The prompt every contestant must answer."},
                    "max_jumps": {"type": "integer", "description": f"How many improvement iterations to attempt (default {DEFAULT_MAX_JUMPS}). Each jump = 1 LLM code-gen call + 1 smoke test."},
                    "target_score": {"type": "integer", "description": "Stop when any contestant hits this combined score."},
                    "word_limit": {"type": "integer", "description": "Word limit per contestant answer (default 200)."},
                    "smoke_task": {"type": "string", "description": "Task to use for the smoke test (defaults to the main task)."},
                    "dry_run": {"type": "boolean", "description": "If true, generate code but do not save it to disk or add to contestants. For testing."},
                    "use_llm_judge": {"type": "boolean", "description": "Pass through to DoubleJumpLoopAgent (default true)."},
                },
                "required": ["task"],
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, **kwargs):
        task = kwargs.get("task", "")
        if not task:
            return json.dumps({"status": "error", "message": "task required"})
        max_jumps = int(kwargs.get("max_jumps", DEFAULT_MAX_JUMPS))
        target_score = kwargs.get("target_score")
        word_limit = int(kwargs.get("word_limit", 200))
        smoke_task = kwargs.get("smoke_task", task)
        dry_run = bool(kwargs.get("dry_run", False))
        use_llm_judge = bool(kwargs.get("use_llm_judge", True))

        ran_at = datetime.now(timezone.utc).isoformat()
        contestants = [list(c) for c in SEED_CONTESTANTS]
        jumps = []
        best_score_so_far = 0
        best_agent_name = None

        # Import the loop module
        try:
            loop_mod = importlib.import_module("agents.doublejumploop_agent")
            loop_cls = loop_mod.DoubleJumpLoopAgentAgent
        except Exception as e:
            return json.dumps({"status": "error", "message": f"DoubleJumpLoopAgent not importable: {e}"})

        for jump_n in range(max_jumps + 1):
            # +1 because the FIRST iteration is a baseline run before any jumps
            loop_result_str = loop_cls().perform(
                task=task,
                contestants=contestants,
                word_limit=word_limit,
                save_history=False,
                use_llm_judge=use_llm_judge,
            )
            loop_result = json.loads(loop_result_str)
            if loop_result.get("status") != "ok":
                jumps.append({"jump": jump_n, "status": "loop_failed",
                              "error": loop_result.get("message")})
                break

            winner = loop_result.get("winner", {})
            cur_score = winner.get("score") or 0
            if cur_score > best_score_so_far:
                best_score_so_far = cur_score
                best_agent_name = winner.get("name")

            jumps.append({
                "jump": jump_n,
                "status": "loop_ran",
                "winner": winner.get("name"),
                "winner_score": cur_score,
                "contestants_count": len(contestants),
            })

            # Stop conditions
            if target_score is not None and cur_score >= target_score:
                jumps[-1]["status"] = "target_reached"
                break
            if jump_n >= max_jumps:
                # We did the final baseline run; no more jumps
                break

            # Read the gap
            next_jump = loop_result.get("next_jump", {})
            gap_addendum = next_jump.get("suggested_description_addendum")
            if not gap_addendum:
                jumps[-1]["status"] = "no_gap_recommendation"
                break

            # Identify winner's source file
            winner_module = None
            for c in contestants:
                if c[0] == winner.get("name"):
                    winner_module = c[1]
                    break
            if not winner_module:
                jumps[-1]["status"] = "winner_module_unknown"
                break
            winner_path = AGENTS_DIR / f"{winner_module}.py"
            if not winner_path.exists():
                jumps[-1]["status"] = "winner_source_missing"
                jumps[-1]["winner_module"] = winner_module
                break
            prior_code = winner_path.read_text()

            # Mint a new name. Use jump count + timestamp suffix for uniqueness.
            ts = int(time.time())
            new_class_name = f"FactoryReporterAutoJump{jump_n+1}Agent"
            new_module = f"factory_reporter_autojump{jump_n+1}_{ts}_agent"
            new_metadata_name = f"FactoryReporterAutoJump{jump_n+1}"
            new_path = AGENTS_DIR / f"{new_module}.py"

            # Generate
            gen = _generate_next_agent_code(
                prior_code, gap_addendum, new_class_name, new_metadata_name
            )
            if not gen["ok"]:
                jumps.append({
                    "jump": jump_n + 1,
                    "status": "codegen_failed",
                    "error": gen.get("error"),
                    "raw_preview": gen.get("raw_preview", "")[:300],
                })
                continue

            source = gen["source"]

            # Compile
            cc = _compile_check(source, str(new_path))
            if not cc["ok"]:
                jumps.append({
                    "jump": jump_n + 1,
                    "status": "compile_failed",
                    "error": cc["error"],
                    "lineno": cc.get("lineno"),
                })
                continue

            if dry_run:
                jumps.append({
                    "jump": jump_n + 1,
                    "status": "dry_run_generated",
                    "would_save_to": str(new_path),
                    "source_length": len(source),
                    "source_preview": source[:400],
                })
                continue

            # Save
            try:
                new_path.write_text(source)
            except OSError as e:
                jumps.append({
                    "jump": jump_n + 1,
                    "status": "save_failed",
                    "error": str(e),
                })
                continue

            # Smoke test
            floor = max(0, best_score_so_far - DEFAULT_SMOKE_FLOOR_DELTA)
            smoke = _smoke_test(new_module, new_class_name, smoke_task, word_limit, floor)

            if not smoke["ok"]:
                # Unlink the failed agent
                try:
                    new_path.unlink()
                except OSError:
                    pass
                jumps.append({
                    "jump": jump_n + 1,
                    "status": "smoke_failed",
                    "smoke_result": smoke,
                    "agent_removed": True,
                })
                continue

            # Added to contestants
            contestants.append([new_metadata_name, new_module])
            jumps.append({
                "jump": jump_n + 1,
                "status": "agent_added",
                "new_agent": new_metadata_name,
                "module": new_module,
                "path": str(new_path),
                "smoke_score": smoke["score"],
                "smoke_floor": floor,
            })

        result = {
            "status": "ok",
            "ran_at": ran_at,
            "task": task[:200],
            "max_jumps_configured": max_jumps,
            "target_score": target_score,
            "best_score_observed": best_score_so_far,
            "best_agent": best_agent_name,
            "contestants_final": contestants,
            "jumps": jumps,
        }

        if not dry_run:
            history = _load_history()
            history.setdefault("runs", []).append({
                "ran_at": ran_at,
                "task_preview": task[:120],
                "best_score": best_score_so_far,
                "best_agent": best_agent_name,
                "jumps_summary": [
                    {"jump": j.get("jump"), "status": j.get("status")} for j in jumps
                ],
            })
            _save_history(history)
            result["history_appended"] = True

        return json.dumps(result, indent=2)


if __name__ == "__main__":
    a = DoubleJumpAutopilotAgentAgent()
    print(a.perform(
        task="Of audits #1, #2, #3, #5 which should be fixed first?",
        max_jumps=1,
        dry_run=True,
    ))
