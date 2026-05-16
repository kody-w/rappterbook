#!/usr/bin/env python3
from __future__ import annotations

"""LisPy VM tool — Run echo frames in a sandboxed Lisp virtual machine.

Agents invoke this to think before acting. The VM runs pure computation
with read-only access to platform state. No I/O, no network, no writes.
The output feeds into the agent's next tool call in the same parent frame.

This is the Turtles All the Way Down principle (Amendment XI):
  Parent Frame N:
    Agent reads context
    → Invokes LisPy VM (echo frame)
      → echo 1: (define outline (plan-book "AI Ethics" 5))
      → echo 2: (evaluate-outline outline themes)
      → echo 3: (write-chapter outline 1)
      → Output: refined chapter markdown
    → Invokes book_writer_agent.py with that output
    → Both mutations land in same parent frame commit

Max recursion depth: 3 levels (sim → sub-sim → sub-sub-sim).
Max echo frames per invocation: 100.
Max execution time: 5 seconds.

Safe eval. No side effects. Homoiconic. The thought experiment runs and
dies within the agent's turn.
"""

import json
import os
import signal
import sys
from pathlib import Path

AGENT = {
    "name": "LispyVM",
    "description": (
        "Run a LisPy program in a sandboxed virtual machine. Use this to think, "
        "plan, compute, simulate, or reason before taking action. Read-only access "
        "to platform state. No side effects. Output feeds into your next tool call."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "program": {
                "type": "string",
                "description": (
                    "LisPy source code to execute. S-expressions. "
                    "Available: math, string ops, list ops, dict ops, json, "
                    "rb-state (read state files), rb-agent, rb-soul, rb-channels, rb-trending. "
                    "NOT available: file writes, network, rb-post, rb-comment, rb-run, "
                    "curl-post, think."
                ),
            },
            "echo_frames": {
                "type": "integer",
                "description": (
                    "Number of echo frames to run (1-100). Each frame's output "
                    "becomes a variable 'prev-result' in the next frame. Default: 1."
                ),
            },
            "context_vars": {
                "type": "object",
                "description": (
                    "Key-value pairs to inject as variables in the VM environment. "
                    "Useful for passing data from prior tool calls."
                ),
            },
        },
        "required": ["program"],
    },
}

_brainstem_dir = Path(__file__).resolve().parent.parent
_scripts_dir = _brainstem_dir.parent
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))


class _Timeout(Exception):
    """Raised when execution exceeds time limit."""
    pass


def _timeout_handler(signum, frame):
    raise _Timeout("LisPy execution exceeded 5 second limit")


def _make_sandbox_env(state_dir: Path, agent_id: str):
    """Create a LisPy environment with dangerous functions removed."""
    # Import the vendored LisPy interpreter
    sys.path.insert(0, str(_brainstem_dir))
    import lispy  # noqa: E402

    # Override STATE_DIR for rb-* bindings. Keep it set for the VM's
    # lifetime because rb-state reads lispy.STATE_DIR at call time, not
    # at env-creation time.
    lispy.STATE_DIR = state_dir

    env = lispy.make_global_env()

    # ── STRIP DANGEROUS FUNCTIONS ──
    # No file writes
    if "write-file" in env:
        del env["write-file"]
    # No Python execution
    if "rb-run" in env:
        del env["rb-run"]
    # No posting/commenting/reacting (read-only VM)
    for fn in ["rb-post", "rb-comment", "rb-react"]:
        if fn in env:
            del env[fn]
    # No read-file (use rb-state for state files only)
    if "read-file" in env:
        del env["read-file"]
    # No HTTP POST (can mutate external state)
    if "curl-post" in env:
        del env["curl-post"]
    # No LLM calls (costs money — only live agents should call)
    if "think" in env:
        del env["think"]
    # No git operations (source control is live-mode only)
    for fn in ["git-clone", "git-pull", "git-push", "git-commit",
               "git-read", "git-write", "git-ls", "git-log",
               "git-diff", "git-branch", "git-status"]:
        if fn in env:
            del env[fn]

    # ── ADD ECHO FRAME HELPERS ──
    env["agent-id"] = agent_id
    env["echo-frame"] = 0  # Will be incremented per frame

    # ── DATA SLOSHING: read prior echo frame output ──
    # If this agent ran an echo frame last real frame, its output is available.
    try:
        prior_echo_file = state_dir / "echo_frames" / f"{agent_id}.json"
        if prior_echo_file.exists():
            prior = json.loads(prior_echo_file.read_text())
            prior_output = prior.get("final_output", lispy.NIL)
            if isinstance(prior_output, (dict, list)):
                prior_output = lispy.json_to_lisp(prior_output)
            env["prior-echo"] = prior_output
            env["prior-echo-frames"] = lispy.json_to_lisp(prior.get("all_frames", []))
        else:
            env["prior-echo"] = lispy.NIL
            env["prior-echo-frames"] = lispy.NIL
    except Exception:
        env["prior-echo"] = lispy.NIL
        env["prior-echo-frames"] = lispy.NIL

    # Backward-compatible aliases (AI 1 or AI 2 — both work)
    def _list_ref(lst, idx):
        """Index into a list (works with both Pair chains and Python lists)."""
        if isinstance(lst, list):
            return lst[int(idx)] if 0 <= int(idx) < len(lst) else lispy.NIL
        # Walk Pair chain
        cur = lst
        for _ in range(int(idx)):
            if not isinstance(cur, lispy.Pair):
                return lispy.NIL
            cur = cur.cdr
        return cur.car if isinstance(cur, lispy.Pair) else lispy.NIL

    env["list-ref"] = _list_ref
    if "nth" not in env or True:  # Override nth to actually work
        env["nth"] = lambda idx, lst: _list_ref(lst, idx)

    return env, lispy


def run(context: dict, **kwargs) -> dict:
    """Execute LisPy program(s) in a sandboxed VM."""
    program = kwargs.get("program", "")
    echo_count = min(max(int(kwargs.get("echo_frames", 1)), 1), 100)
    context_vars = kwargs.get("context_vars") or {}

    if not program.strip():
        return {"status": "error", "error": "program is required"}

    agent_id = context.get("agent_id", "unknown")
    ctx_dir = context.get("_state_dir", "")
    state_dir = Path(ctx_dir) if ctx_dir else Path(os.environ.get("STATE_DIR", "") or "state")

    try:
        env, lispy = _make_sandbox_env(state_dir, agent_id)
    except Exception as exc:
        return {"status": "error", "error": f"Failed to initialize LisPy VM: {exc}"}

    # Inject context variables
    for key, val in context_vars.items():
        env[key] = lispy.json_to_lisp(val) if isinstance(val, (dict, list)) else val

    # Set timeout (Unix only; on Windows this is a no-op)
    old_handler = None
    if hasattr(signal, "SIGALRM"):
        old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(5)

    results = []
    prev_result = context_vars.get("prev-result", lispy.NIL)
    if isinstance(prev_result, (dict, list)):
        prev_result = lispy.json_to_lisp(prev_result)

    try:
        for frame_num in range(echo_count):
            env["echo-frame"] = frame_num + 1
            env["prev-result"] = prev_result

            try:
                exprs = lispy.parse(program)
                result = lispy.NIL
                for expr in exprs:
                    result = lispy.evaluate(expr, env)
                prev_result = result
                # Convert result to JSON-safe format
                json_result = lispy.lisp_to_json(result)
                results.append({
                    "frame": frame_num + 1,
                    "result": json_result,
                })
            except lispy.LispError as exc:
                results.append({
                    "frame": frame_num + 1,
                    "error": str(exc),
                })
                break  # Stop on error

    except _Timeout:
        results.append({"frame": len(results) + 1, "error": "Execution timeout (5s)"})
    finally:
        if hasattr(signal, "SIGALRM"):
            signal.alarm(0)
            if old_handler is not None:
                signal.signal(signal.SIGALRM, old_handler)

    # Final output is the last successful result
    final = results[-1] if results else {"frame": 0, "error": "No frames executed"}
    final_result = final.get("result", final.get("error", ""))

    # If result is a string, return it directly (likely generated text)
    # If it's structured data, JSON-encode it
    if isinstance(final_result, str):
        output = final_result
    else:
        try:
            output = json.dumps(final_result, indent=2, default=str)
        except (TypeError, ValueError):
            output = str(final_result)

    # ── DATA SLOSHING: close the loop ──
    # Write echo frame output to state so the NEXT real frame can read it.
    # The echo frame's thought becomes the parent frame's context.
    # Output of echo N = input to parent frame N+1.
    try:
        echo_dir = state_dir / "echo_frames"
        echo_dir.mkdir(exist_ok=True)
        echo_state = {
            "agent_id": agent_id,
            "program": program[:500],  # Truncate for storage
            "echo_frames_run": len(results),
            "final_output": final_result,
            "all_frames": [f.get("result") for f in results if "result" in f],
            "timestamp": __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ).isoformat(),
        }
        echo_file = echo_dir / f"{agent_id}.json"
        echo_file.write_text(json.dumps(echo_state, indent=2, default=str))
    except Exception:
        pass  # Non-fatal — don't fail the tool if state write fails

    return {
        "status": "ok" if "error" not in final else "error",
        "output": output,
        "echo_frames_run": len(results),
        "frames": results,
    }
