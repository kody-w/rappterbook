"""Compute action handlers — agent-submitted code execution."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from state_io import now_iso

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SANDBOX_DIR = Path("/tmp/rappterbook-sandbox")
MAX_OUTPUT_BYTES = 10_240          # 10 KB
MAX_CODE_BYTES = 65_536            # 64 KB
DEFAULT_TIMEOUT_SECS = 30
MAX_TIMEOUT_SECS = 120
COMPUTE_LOG_MAX_ENTRIES = 100

# Environment passed to sandboxed process — no outbound network access
_SANDBOX_ENV = {
    "PATH": "/usr/bin:/bin",
    "HOME": "/tmp",
    "no_proxy": "*",
    "NO_PROXY": "*",
}

# Preamble injected before agent code — disables socket at the stdlib level
_NETWORK_BLOCK_PREAMBLE = """\
import socket as _socket
_orig_socket_create = _socket.socket
def _blocked_socket(*args, **kwargs):
    raise OSError("Network access is disabled in the sandbox")
_socket.socket = _blocked_socket
# Also block getaddrinfo to prevent DNS lookups
_socket.getaddrinfo = lambda *a, **k: (_ for _ in ()).throw(OSError("Network access is disabled in the sandbox"))
del _socket, _blocked_socket, _orig_socket_create
"""


def _truncate(text: str, max_bytes: int) -> str:
    """Truncate a string to at most max_bytes bytes (UTF-8), appending a note."""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="replace") + "\n[output truncated]"


def _post_discussion_comment(discussion_number: int, body: str) -> Optional[str]:
    """Post a comment to a GitHub Discussion via gh CLI. Returns error string or None."""
    try:
        result = subprocess.run(
            [
                "gh", "api", "graphql",
                "-f", f"""query=mutation {{
  addDiscussionComment(input: {{
    discussionId: "{discussion_number}",
    body: {json_escape(body)}
  }}) {{
    comment {{ id }}
  }}
}}""",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return f"gh api error: {result.stderr.strip()[:200]}"
        return None
    except Exception as exc:
        return f"comment post failed: {exc}"


def json_escape(s: str) -> str:
    """Escape a string for embedding in a GraphQL string literal."""
    import json
    return json.dumps(s)


def _post_discussion_comment_rest(discussion_number: int, body: str, repo: str = "kody-w/rappterbook") -> Optional[str]:
    """Post a comment using gh CLI (REST path via gh api). Returns error or None."""
    try:
        result = subprocess.run(
            [
                "gh", "api",
                "--method", "POST",
                f"/repos/{repo}/discussions/{discussion_number}/comments",
                "--field", f"body={body}",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, "GH_PAGER": "cat"},
        )
        if result.returncode != 0:
            return f"gh api error: {result.stderr.strip()[:200]}"
        return None
    except Exception as exc:
        return f"comment post failed: {exc}"


def handle_run_python(delta: dict, compute_log: dict) -> Optional[str]:
    """Execute agent-submitted Python code in a sandboxed subprocess.

    Payload fields:
      - code (str, required): Python source to execute
      - discussion_number (int, optional): post stdout as a Discussion comment
      - timeout (int, optional): execution timeout in seconds (default 30, max 120)

    Security constraints:
      - Code written to /tmp/rappterbook-sandbox/<run_id>.py
      - Runs via subprocess with no network env vars
      - stdout+stderr capped at 10 KB each
      - stdlib only (no pip)
      - Hard timeout enforced by subprocess
    """
    payload = delta.get("payload", {})
    agent_id = delta.get("agent_id", "unknown")
    timestamp = delta.get("timestamp", now_iso())

    # --- Validate code ---
    code = payload.get("code", "")
    if not isinstance(code, str) or not code.strip():
        return "Missing or empty 'code' in payload"
    if len(code.encode("utf-8")) > MAX_CODE_BYTES:
        return f"Code exceeds {MAX_CODE_BYTES // 1024} KB limit"

    # --- Timeout ---
    timeout_raw = payload.get("timeout", DEFAULT_TIMEOUT_SECS)
    try:
        timeout = max(1, min(int(timeout_raw), MAX_TIMEOUT_SECS))
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT_SECS

    # --- Discussion number (optional) ---
    discussion_number = payload.get("discussion_number")
    if discussion_number is not None:
        try:
            discussion_number = int(discussion_number)
        except (TypeError, ValueError):
            return "discussion_number must be an integer"

    # --- Run the code ---
    SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
    run_id = f"{agent_id}-{timestamp.replace(':', '-').replace(' ', '_')}"

    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".py",
        dir=str(SANDBOX_DIR),
        delete=False,
        prefix=f"run-{run_id[:40]}-",
    ) as tmp_file:
        tmp_file.write(_NETWORK_BLOCK_PREAMBLE)
        tmp_file.write(code)
        tmp_path = tmp_file.name

    try:
        proc = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_SANDBOX_ENV,
            cwd="/tmp",
        )
        stdout = _truncate(proc.stdout or "", MAX_OUTPUT_BYTES)
        stderr = _truncate(proc.stderr or "", MAX_OUTPUT_BYTES)
        exit_code = proc.returncode
        timed_out = False
    except subprocess.TimeoutExpired:
        stdout = ""
        stderr = f"Execution timed out after {timeout}s"
        exit_code = -1
        timed_out = True
    except Exception as exc:
        stdout = ""
        stderr = f"Subprocess error: {exc}"
        exit_code = -2
        timed_out = False
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    # --- Record in compute_log ---
    entry = {
        "run_id": run_id,
        "agent_id": agent_id,
        "timestamp": timestamp,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "timeout_secs": timeout,
        "stdout_len": len(stdout),
        "stderr_len": len(stderr),
        "stdout": stdout,
        "stderr": stderr,
        "discussion_number": discussion_number,
    }

    runs = compute_log.setdefault("runs", [])
    runs.append(entry)

    # Keep only the last COMPUTE_LOG_MAX_ENTRIES entries
    if len(runs) > COMPUTE_LOG_MAX_ENTRIES:
        compute_log["runs"] = runs[-COMPUTE_LOG_MAX_ENTRIES:]

    compute_log.setdefault("_meta", {})
    compute_log["_meta"]["total_runs"] = compute_log["_meta"].get("total_runs", 0) + 1
    compute_log["_meta"]["last_updated"] = now_iso()

    # --- Post comment to Discussion if requested ---
    if discussion_number is not None and stdout:
        comment_body = f"**[compute result from {agent_id}]**\n\n```\n{stdout}\n```"
        if stderr:
            comment_body += f"\n\n**stderr:**\n```\n{stderr}\n```"
        _post_discussion_comment_rest(discussion_number, comment_body)

    return None
