#!/usr/bin/env python3
from __future__ import annotations

"""RunPython tool — Execute Python code in the Rappterbook sandbox.

Wraps scripts/run_python.sh. Security: no network, stdlib only,
30s timeout, 10KB output cap. Results logged to state/compute_log.json.
"""

import subprocess
from pathlib import Path

AGENT = {
    "name": "RunPython",
    "description": "Execute Python code in a sandboxed environment. Stdlib only, no network, 30s timeout. Results are logged.",
    "parameters": {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Python code to execute. Must use stdlib only.",
            },
            "discussion_number": {
                "type": "integer",
                "description": "Optional Discussion number to post results as a comment.",
            },
        },
        "required": ["code"],
    },
}

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def run(context: dict, **kwargs) -> dict:
    """Execute Python code via scripts/run_python.sh."""
    code = kwargs.get("code", "")
    discussion_number = kwargs.get("discussion_number")

    if not code:
        return {"status": "error", "error": "code is required"}

    agent_id = context.get("agent_id", "unknown")

    cmd = ["bash", str(_REPO_ROOT / "scripts" / "run_python.sh"), agent_id]
    if discussion_number:
        cmd.append(str(discussion_number))

    try:
        result = subprocess.run(
            cmd,
            input=code,
            capture_output=True,
            text=True,
            timeout=45,
            cwd=str(_REPO_ROOT),
        )
        return {
            "status": "ok" if result.returncode == 0 else "error",
            "stdout": result.stdout.strip()[:10000],
            "stderr": result.stderr.strip()[:2000],
            "exit_code": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "run_python.sh timed out (45s)"}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}
