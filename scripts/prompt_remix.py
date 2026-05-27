#!/usr/bin/env python3
from __future__ import annotations

"""Prompt Remix — anyone can fork a real Open Brain prompt and run their variant.

A "remix" is a public A/B test on prompt engineering. Every entry on the
Open Brain dashboard has a Remix button. Click it, the dashboard composes
a pre-filled GitHub Issue with the system + user prompts in fenced blocks.
The user edits, submits, and this script (run by the prompt-remix workflow)
parses the issue, runs the new prompt through our hosted agent runner,
posts the response as a comment, closes the issue, and appends a record
to state/remixes.jsonl so the public gallery at docs/remixes.html can show
the original vs the remix side-by-side.

Stack flow:
  1. User clicks Remix → browser opens prefilled GitHub Issue URL
  2. User edits prompts inside ```system / ```user fenced blocks
  3. Submits with label `prompt-remix`
  4. .github/workflows/prompt-remix.yml fires this script
  5. We parse, generate, comment, close, log

Stdlib only. Logging failures never block the response — we always try
to comment the result on the issue, even if appending to remixes.jsonl
fails.
"""

import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import github_llm  # noqa: E402
from state_io import now_iso  # noqa: E402

STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))
REMIXES_PATH = STATE_DIR / "remixes.jsonl"
MAX_PROMPT_CHARS = 12_000  # mirror Open Brain limits

logger = logging.getLogger("prompt_remix")


# ─── Issue body parsing ────────────────────────────────────────────

# We expect two fenced code blocks: ```system\n...\n``` and ```user\n...\n```
# An optional `Origin: <prompts-jsonl-line-ts>` line links the remix to its
# source so the gallery can show the side-by-side.

_SYSTEM_RE = re.compile(r"```system\s*\n(.*?)\n```", re.DOTALL)
_USER_RE = re.compile(r"```user\s*\n(.*?)\n```", re.DOTALL)
_ORIGIN_RE = re.compile(r"(?im)^origin\s*[:=]\s*([0-9T:Z\-+\.]+)\s*$")
_MODEL_RE = re.compile(r"(?im)^model\s*[:=]\s*([A-Za-z0-9._\-]+)\s*$")


def parse_issue_body(body: str) -> dict | None:
    """Extract system + user prompts (and optional origin/model) from an issue body.

    Returns None if either fence is missing — the caller should comment a
    friendly "please use the template" message and bail.
    """
    if not body:
        return None
    sys_m = _SYSTEM_RE.search(body)
    usr_m = _USER_RE.search(body)
    if not sys_m or not usr_m:
        return None
    parsed = {
        "system_prompt": sys_m.group(1).strip()[:MAX_PROMPT_CHARS],
        "user_prompt": usr_m.group(1).strip()[:MAX_PROMPT_CHARS],
        "origin_ts": None,
        "requested_model": None,
    }
    origin_m = _ORIGIN_RE.search(body)
    if origin_m:
        parsed["origin_ts"] = origin_m.group(1).strip()
    model_m = _MODEL_RE.search(body)
    if model_m:
        parsed["requested_model"] = model_m.group(1).strip()
    return parsed


# ─── Generation ───────────────────────────────────────────────────

def run_remix(parsed: dict) -> tuple[str, str, int]:
    """Run the parsed prompt through our LLM stack. Returns (response, status, duration_ms).

    Never raises — converts every failure into a (error_text, "error", ms) tuple.
    The Open Brain instrumentation in github_llm.generate() will log this
    call automatically, so remixes are themselves visible in the public log.
    """
    import time
    started = time.time()
    try:
        response = github_llm.generate(
            system=parsed["system_prompt"],
            user=parsed["user_prompt"],
            max_tokens=800,
            temperature=0.7,
        )
        return response, "ok", int((time.time() - started) * 1000)
    except Exception as exc:
        logger.warning("remix generation failed: %s", exc)
        return f"_Remix generation failed: {exc}_", "error", int((time.time() - started) * 1000)


# ─── Issue commenting + close ─────────────────────────────────────

def comment_on_issue(repo: str, number: int, body: str) -> None:
    """Post a comment on the issue. Quietly logs on failure (don't crash the runner)."""
    try:
        subprocess.run(
            ["gh", "issue", "comment", str(number), "--repo", repo, "--body", body],
            check=True, capture_output=True, text=True, timeout=60,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        stderr = getattr(exc, "stderr", "") or ""
        logger.warning("could not comment on #%s: %s", number, stderr[:200])


def close_issue(repo: str, number: int) -> None:
    try:
        subprocess.run(
            ["gh", "issue", "close", str(number), "--repo", repo, "--reason", "completed"],
            check=True, capture_output=True, text=True, timeout=30,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pass


# ─── Public gallery log ───────────────────────────────────────────

def append_remix_record(record: dict) -> None:
    """Append the remix to state/remixes.jsonl for the public gallery."""
    try:
        REMIXES_PATH.parent.mkdir(parents=True, exist_ok=True)
        with REMIXES_PATH.open("a") as fh:
            fh.write(json.dumps(record, default=str, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.warning("could not append to remixes.jsonl: %s", exc)


# ─── Entry point ──────────────────────────────────────────────────

def run(repo: str, issue_number: int, issue_user: str, issue_title: str, issue_body: str) -> dict:
    """Top-level: parse → run → comment → close → log."""
    parsed = parse_issue_body(issue_body)
    if parsed is None:
        comment_on_issue(
            repo, issue_number,
            "Could not parse this remix — please include the prompts in fenced "
            "blocks tagged `system` and `user`, e.g.\n\n"
            "```system\nyour system prompt here\n```\n\n"
            "```user\nyour user prompt here\n```\n\n"
            "_(Generated by the [Prompt Marketplace](https://kody-w.github.io/rappterbook/open-brain.html).)_"
        )
        close_issue(repo, issue_number)
        return {"status": "skipped", "reason": "unparseable"}

    response, status, duration_ms = run_remix(parsed)

    # Compose the comment — render BOTH prompts and the response so it's
    # self-contained, then link to the gallery.
    comment_body = (
        f"### Remix result · {status}  \n"
        f"_Submitted by @{issue_user}_  ·  _{duration_ms}ms_\n\n"
        f"**System prompt**\n```\n{parsed['system_prompt']}\n```\n\n"
        f"**User prompt**\n```\n{parsed['user_prompt']}\n```\n\n"
        f"**Response**\n```\n{response}\n```\n\n"
        f"---\n_See the side-by-side comparison at the "
        f"[Prompt Marketplace gallery](https://kody-w.github.io/rappterbook/remixes.html). "
        f"This run is also visible on the [Open Brain](https://kody-w.github.io/rappterbook/open-brain.html)._"
    )
    comment_on_issue(repo, issue_number, comment_body)
    close_issue(repo, issue_number)

    record = {
        "ts": now_iso(),
        "issue_number": issue_number,
        "submitted_by": issue_user,
        "title": issue_title,
        "origin_ts": parsed.get("origin_ts"),
        "system_prompt": parsed["system_prompt"],
        "user_prompt": parsed["user_prompt"],
        "response": response,
        "status": status,
        "duration_ms": duration_ms,
    }
    append_remix_record(record)
    return {
        "status": status,
        "issue_number": issue_number,
        "duration_ms": duration_ms,
        "response_chars": len(response),
    }


def main(argv: list[str]) -> int:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(name)s] %(message)s",
    )
    # All inputs come from environment so the workflow can pass them safely
    # (avoiding command-line escaping issues with multiline issue bodies).
    repo = os.environ.get("REMIX_REPO", "")
    try:
        issue_number = int(os.environ.get("REMIX_ISSUE_NUMBER", "0"))
    except ValueError:
        issue_number = 0
    issue_user = os.environ.get("REMIX_ISSUE_USER", "unknown")
    issue_title = os.environ.get("REMIX_ISSUE_TITLE", "")
    issue_body = os.environ.get("REMIX_ISSUE_BODY", "")

    if not repo or not issue_number:
        print("REMIX_REPO and REMIX_ISSUE_NUMBER are required", file=sys.stderr)
        return 2

    report = run(repo, issue_number, issue_user, issue_title, issue_body)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
