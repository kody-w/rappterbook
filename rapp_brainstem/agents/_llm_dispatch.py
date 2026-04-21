"""
LLM dispatch — route agent LLM calls to whichever backend has capacity.

Default backend is claude CLI (opus-4-7 1M context), set via AGENT_LLM_BACKEND
env var: "claude" (default) | "github".

claude backend: subprocess.run claude -p --model claude-opus-4-7 --output-format text
github backend: scripts/github_llm.py's generate()
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

_BACKEND = os.environ.get("AGENT_LLM_BACKEND", "claude").lower()
_CLAUDE_MODEL = os.environ.get("CLAUDE_CLI_MODEL", "claude-opus-4-7")
_CLAUDE_BIN = shutil.which("claude") or "/Users/kodyw/.local/bin/claude"


def _call_claude_cli(system: str, user: str, max_tokens: int) -> str:
    """One-shot claude CLI call. Returns text or raises."""
    prompt = f"{system.strip()}\n\n---\n\n{user.strip()}"
    result = subprocess.run(
        [_CLAUDE_BIN, "-p",
         "--model", _CLAUDE_MODEL,
         "--dangerously-skip-permissions",
         "--allowedTools", "",
         "--output-format", "text"],
        input=prompt, capture_output=True, text=True, timeout=180,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude CLI failed ({result.returncode}): {result.stderr[:400]}")
    return result.stdout.strip()


def _call_github_llm(system: str, user: str, max_tokens: int,
                      temperature: float) -> str:
    """Fallback to scripts/github_llm.generate()."""
    here = Path(__file__).resolve()
    for p in [here, *here.parents]:
        scripts = p.parent / "scripts" if p.name == "rapp_brainstem" else p / "scripts"
        if scripts.is_dir() and (scripts / "github_llm.py").exists():
            if str(scripts) not in sys.path:
                sys.path.insert(0, str(scripts))
            break
    from github_llm import generate
    return generate(system=system, user=user, max_tokens=max_tokens,
                    temperature=temperature)


def generate(system: str, user: str, max_tokens: int = 1500,
              temperature: float = 0.75) -> str:
    """Route to the configured backend."""
    backend = os.environ.get("AGENT_LLM_BACKEND", _BACKEND).lower()
    if backend == "claude":
        try:
            return _call_claude_cli(system, user, max_tokens)
        except Exception as exc:  # noqa: BLE001
            fallback = os.environ.get("AGENT_LLM_FALLBACK", "github")
            if fallback == "github":
                print(f"[llm_dispatch] claude CLI failed ({exc}); falling back to github_llm",
                      file=sys.stderr)
                return _call_github_llm(system, user, max_tokens, temperature)
            raise
    return _call_github_llm(system, user, max_tokens, temperature)
