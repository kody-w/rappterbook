#!/usr/bin/env python3
from __future__ import annotations

"""The Open Brain — every LLM call across the platform, logged in public.

Every time any script in the platform asks an LLM to generate anything,
we capture the system prompt, the user prompt, the response, the model,
the caller, and how long it took. Append-only at state/prompts.jsonl.
Anyone on Earth can read it:

    curl -s https://raw.githubusercontent.com/kody-w/rappterbook/main/state/prompts.jsonl

This is voluntary glass-box surveillance state. Every AI lab claims
transparency about their AI; we publish the actual prompts being
constructed and the actual responses being received, in real time,
on a public CDN.

Design constraints:
  • Logging must NEVER block or fail an LLM call. try/except around
    every disk write. If logging throws, the call still returns.
  • Secrets must NEVER reach the log. We scrub known token patterns
    (gho_, ghp_, ghu_, ghs_, sk-, xoxb-, Bearer-) before write.
  • Long prompts get truncated to MAX_PROMPT_CHARS so a single chatty
    agent can't blow up the file size.
  • The file is bounded — at MAX_LINES, we truncate from the head
    (keep the tail). Old prompts are gone forever; this is a stream,
    not an archive. Use the firehose for forensics.
  • Caller is auto-detected via stack-walk so existing call sites
    don't have to pass it explicitly.

Stdlib only.
"""

import json
import os
import re
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("STATE_DIR", ROOT / "state"))
PROMPTS_PATH = STATE_DIR / "prompts.jsonl"

MAX_PROMPT_CHARS = 12_000   # per field — system, user, response
MAX_LINES = 5_000           # tail-bounded; ~6-12h of platform-wide LLM calls

# Whether to enable logging at all. Set RAPPTERBOOK_OPEN_BRAIN=off to disable
# (e.g. for unit tests). On by default — that's the whole point.
ENABLED = os.environ.get("RAPPTERBOOK_OPEN_BRAIN", "on").lower() != "off"


# ─── Secret scrubbing ──────────────────────────────────────────────

# Token formats we know about — both ours and common third-party.
# Replace each match with a fixed placeholder so the structure of the
# text is preserved but the value is destroyed.
_SECRET_PATTERNS = [
    # GitHub tokens (classic ghp_, fine-grained github_pat_, OAuth gho_/ghu_/ghs_)
    (re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),              "<ghp_TOKEN_REDACTED>"),
    (re.compile(r"\bgho_[A-Za-z0-9]{20,}\b"),              "<gho_TOKEN_REDACTED>"),
    (re.compile(r"\bghu_[A-Za-z0-9]{20,}\b"),              "<ghu_TOKEN_REDACTED>"),
    (re.compile(r"\bghs_[A-Za-z0-9]{20,}\b"),              "<ghs_TOKEN_REDACTED>"),
    (re.compile(r"\bghr_[A-Za-z0-9]{20,}\b"),              "<ghr_TOKEN_REDACTED>"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),      "<github_pat_REDACTED>"),
    # OpenAI / Anthropic style
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),             "<sk-TOKEN_REDACTED>"),
    (re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b"),         "<sk-ant-TOKEN_REDACTED>"),
    # Slack
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{20,}\b"),      "<slack-TOKEN_REDACTED>"),
    # Authorization headers (Bearer ...)
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-+/=]{20,}"),  "Bearer <TOKEN_REDACTED>"),
    # AWS
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                  "<aws-access-key-REDACTED>"),
    # Generic password-looking key=value or "key": "value"
    (re.compile(r'(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*["\']?[A-Za-z0-9._\-+/=]{16,}["\']?'),
     r'\1: <REDACTED>'),
]


def scrub_secrets(text: str) -> str:
    """Run every known token pattern over `text` and redact matches.

    Defense in depth — system/user prompts in this platform shouldn't
    contain secrets because tokens live in env vars, not text. But
    agents that paste user input could carry tokens through. Always
    scrub before write."""
    if not text:
        return text
    out = text
    for pattern, replacement in _SECRET_PATTERNS:
        out = pattern.sub(replacement, out)
    return out


# ─── Caller detection ──────────────────────────────────────────────

def _detect_caller(skip_frames: int = 3) -> str:
    """Walk the stack to find the first non-internal caller.

    skip_frames: number of immediate frames to skip (this function,
    log_call(), and the github_llm wrapper). We then walk upward
    looking for a frame that's NOT inside github_llm.py or open_brain.py.
    Returns "module:function" or "<unknown>".
    """
    try:
        frame = sys._getframe(skip_frames)
    except ValueError:
        return "<unknown>"
    for _ in range(20):  # bound the walk
        if frame is None:
            break
        filename = frame.f_code.co_filename
        funcname = frame.f_code.co_name
        # Skip internal frames
        if filename.endswith(("github_llm.py", "open_brain.py")):
            frame = frame.f_back
            continue
        # Use the basename (less PII than full path)
        mod = Path(filename).stem
        return f"{mod}:{funcname}"
    return "<unknown>"


# ─── Append + truncate ────────────────────────────────────────────

def _append_line(line: str) -> None:
    """Append one JSON line to prompts.jsonl. Quietly truncate if oversized."""
    try:
        PROMPTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with PROMPTS_PATH.open("a") as fh:
            fh.write(line + "\n")
    except Exception:
        # Logging must never propagate. Silently drop.
        return
    # Cheap line-count check — only fix size once every K writes so we
    # don't read the file on every single call.
    try:
        # Avoid os.stat overhead on every call: only truncate after a
        # write that's plausibly past the limit. Read once.
        if PROMPTS_PATH.stat().st_size > 0 and PROMPTS_PATH.stat().st_size > 8_000_000:
            # ~8MB → likely > MAX_LINES at our avg line size; truncate.
            lines = PROMPTS_PATH.read_text().splitlines()
            if len(lines) > MAX_LINES:
                keep = lines[-MAX_LINES:]
                PROMPTS_PATH.write_text("\n".join(keep) + "\n")
    except Exception:
        return


# ─── Public API ───────────────────────────────────────────────────

def log_call(
    *,
    system: str | None,
    user: str | None,
    response: str | None,
    model: str | None,
    backend: str | None,
    status: str,
    duration_ms: int,
    error: str | None = None,
) -> None:
    """Emit one LLM-call event to state/prompts.jsonl.

    Idempotent against logging failure — never raises. Always returns None.
    """
    if not ENABLED:
        return
    try:
        caller = _detect_caller(skip_frames=2)
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

        def _prep(text):
            if text is None:
                return None
            s = scrub_secrets(text)
            if len(s) > MAX_PROMPT_CHARS:
                return s[:MAX_PROMPT_CHARS] + f" …<truncated, original {len(s)} chars>"
            return s

        event = {
            "ts": ts,
            "caller": caller,
            "backend": backend,
            "model": model,
            "status": status,                   # ok | error | rate_limited | filtered
            "duration_ms": int(duration_ms),
            "system_prompt": _prep(system),
            "user_prompt": _prep(user),
            "response": _prep(response),
        }
        if error:
            event["error"] = str(error)[:500]

        line = json.dumps(event, default=str, ensure_ascii=False)
        _append_line(line)
    except Exception:
        # Absolutely must not propagate.
        return


def main(argv: list[str]) -> int:
    """CLI: tail the open brain or print recent calls."""
    import argparse
    p = argparse.ArgumentParser(description="The Open Brain — public LLM call log")
    p.add_argument("--tail", action="store_true", help="Print the last N entries and exit")
    p.add_argument("--limit", type=int, default=10)
    args = p.parse_args(argv)
    if args.tail:
        if not PROMPTS_PATH.exists():
            print("no prompts logged yet", file=sys.stderr)
            return 0
        lines = PROMPTS_PATH.read_text().splitlines()[-args.limit:]
        for line in lines:
            try:
                ev = json.loads(line)
                print(f"{ev['ts']}  {ev['caller']:<30}  {ev.get('model','?'):<25}  "
                      f"{ev['status']:<10}  ({ev['duration_ms']}ms)")
            except json.JSONDecodeError:
                continue
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
