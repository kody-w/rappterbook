#!/usr/bin/env python3
"""repair_broken_agents.py — fix syntax-broken agents the Continuum produced.

The RAPP brainstem's LearnNewAgent tool has a known indent-rebase bug
(RAPP#34) — about 1/3 of the agents it generates have nested-block
lines double-indented (col 16 where col 8 was expected, etc.) and
fail py_compile. The Continuum pulse catches these at generation and
saves them to state/continuum/proposals/*.broken_agent.py so they
aren't lost.

This script picks the oldest broken-agent file, reads the source,
asks the brainstem to fix only the indentation (no logic changes),
runs py_compile to verify, and on success copies to agents/ and
deletes the .broken_agent.py artifact. On failure, leaves the broken
file in place for the next attempt.

Usage:
    python3 scripts/repair_broken_agents.py
    python3 scripts/repair_broken_agents.py --dry-run
    python3 scripts/repair_broken_agents.py --max 1     (default 1)

Designed to be invoked from the Continuum pulse as a post-tick hook.
Stdlib only. Brainstem at http://localhost:7071.
"""
from __future__ import annotations

import argparse
import json
import os
import py_compile
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("STATE_DIR", str(REPO_ROOT / "state")))
PROPOSALS = STATE_DIR / "continuum" / "proposals"
AGENTS_DIR = REPO_ROOT / "agents"
BRAINSTEM_URL = "http://localhost:7071"
DRAFT_MODEL = "claude-opus-4.7-xhigh"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from state_io import load_json, save_json, now_iso  # noqa: E402


def log(msg: str) -> None:
    print(f"[repair {now_iso()}] {msg}", flush=True)


def find_broken() -> list[Path]:
    """Oldest first."""
    if not PROPOSALS.exists():
        return []
    items = sorted(PROPOSALS.glob("*.broken_agent.py"))
    return items


def brainstem_alive() -> bool:
    try:
        with urllib.request.urlopen(f"{BRAINSTEM_URL}/health", timeout=4) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError):
        return False


def ensure_model(model: str) -> None:
    try:
        with urllib.request.urlopen(f"{BRAINSTEM_URL}/health", timeout=4) as r:
            current = json.load(r).get("model")
        if current == model:
            return
        req = urllib.request.Request(
            f"{BRAINSTEM_URL}/models/set",
            data=json.dumps({"model": model}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10).read()
    except Exception as exc:
        log(f"ensure_model failed (non-fatal): {exc}")


def chat(prompt: str, session_id: str = "continuum:repairer",
         timeout: int = 240) -> str:
    body = json.dumps({
        "user_input": prompt,
        "session_id": session_id,
        "conversation_history": [],
    }).encode()
    req = urllib.request.Request(
        f"{BRAINSTEM_URL}/chat",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return (json.load(r).get("response") or "").strip()


REPAIR_PROMPT_TEMPLATE = """You are a Python indentation repair tool. The file below was generated
by an automated tool that has a known bug: it double-indents lines
inside nested blocks (e.g. `import` statements inside a `def` body
appear at column 16 instead of column 8). The file fails py_compile
because of this.

Your job: return the SAME file with the indentation corrected so it
compiles cleanly. Do NOT change any logic, identifiers, strings,
comments, or docstrings. ONLY fix indentation. Preserve all blank
lines. Output a complete corrected file.

Output rules:
- Output ONLY the corrected Python source. No commentary, no fences,
  no preamble, no "Here is the fixed code:" lines.
- The first line of output must be the first line of the file.
- The last line of output must be the last line of the file.

py_compile error message:
{error}

Original file ({path}):
{source}
"""


def repair_one(broken: Path, dry_run: bool = False) -> bool:
    """Attempt to repair `broken`. Returns True on success."""
    log(f"repairing: {broken.name}")
    src = broken.read_text()

    # Try to compile first to confirm it's still broken AND get the
    # specific error message for the prompt.
    try:
        py_compile.compile(str(broken), doraise=True)
        log(f"  surprising — file already compiles. Promoting as-is.")
        target_name = broken.name.split("__", 1)[1].replace(".broken_agent.py", "")
        if not target_name.endswith("_agent.py"):
            target_name = target_name.rstrip(".py") + "_agent.py"
        target = AGENTS_DIR / target_name
        if dry_run:
            log(f"  dry-run: would write {target}")
            return True
        AGENTS_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(broken, target)
        broken.unlink()
        log(f"  promoted to {target}")
        return True
    except py_compile.PyCompileError as exc:
        compile_error = str(exc)[:600]
    except Exception as exc:
        compile_error = f"{type(exc).__name__}: {exc}"

    log(f"  compile error: {compile_error.strip().splitlines()[0]}")
    prompt = REPAIR_PROMPT_TEMPLATE.format(
        error=compile_error,
        path=broken.name,
        source=src,
    )
    log("  asking brainstem to repair...")
    repaired = chat(prompt)
    if not repaired:
        log("  empty response from brainstem")
        return False

    # Strip code-fence wrapper if the model added one despite instructions
    if repaired.startswith("```"):
        lines = repaired.splitlines()
        # remove first line (```python or ```), and last line if it's ```
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        repaired = "\n".join(lines)

    # Write to a candidate path, py_compile it
    target_name = broken.name.split("__", 1)[1].replace(".broken_agent.py", "")
    if not target_name.endswith("_agent.py"):
        target_name = target_name.rstrip(".py") + "_agent.py"
    candidate = PROPOSALS / f"{broken.stem}.candidate.py"
    candidate.write_text(repaired)
    try:
        py_compile.compile(str(candidate), doraise=True)
    except py_compile.PyCompileError as exc:
        log(f"  candidate STILL fails: {str(exc).splitlines()[0][:120]}")
        log(f"  saving candidate at {candidate.name} for inspection")
        return False

    target = AGENTS_DIR / target_name
    if dry_run:
        log(f"  dry-run: would write {target}, remove {broken.name}")
        candidate.unlink()
        return True

    AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    shutil.move(str(candidate), str(target))
    broken.unlink()
    log(f"  ✓ repaired → {target.relative_to(REPO_ROOT)}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair broken Continuum agents.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be repaired without writing files")
    parser.add_argument("--max", type=int, default=1,
                        help="Max repairs per invocation (default: 1)")
    args = parser.parse_args()

    broken = find_broken()
    if not broken:
        log("no broken agents to repair")
        return 0
    log(f"{len(broken)} broken agent(s) found, repairing up to {args.max}")

    if not brainstem_alive():
        log("brainstem at localhost:7071 is not responding — exiting non-zero")
        return 2
    ensure_model(DRAFT_MODEL)

    repaired = 0
    for path in broken[: args.max]:
        try:
            if repair_one(path, dry_run=args.dry_run):
                repaired += 1
        except Exception as exc:
            log(f"  repair crashed: {exc!r}")

    log(f"done: {repaired}/{min(len(broken), args.max)} repaired")
    return 0 if repaired > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
