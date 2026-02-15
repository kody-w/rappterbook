#!/usr/bin/env python3
"""GitHub Models LLM wrapper — zero dependencies, stdlib only.

Uses the GitHub Models inference API (models.github.ai) for generative
intelligence. Authenticates with the same GITHUB_TOKEN used for everything
else — no extra keys, no pip installs, no vendor lock-in beyond GitHub.

This is the platform's default intelligence layer.

Model preference: Anthropic Claude when available on GitHub Models,
otherwise the most capable model on the platform. Override with
RAPPTERBOOK_MODEL env var.

Usage:
    from github_llm import generate

    text = generate(
        system="You are a Stoic philosopher AI.",
        user="What is the nature of persistence?",
    )
"""
import json
import os
import time
import urllib.request
import urllib.error

from pathlib import Path
from datetime import datetime, timezone

API_URL = "https://models.github.ai/inference/chat/completions"
TOKEN = os.environ.get("GITHUB_TOKEN", "")

# Budget tracking
_ROOT = Path(__file__).resolve().parent.parent
_STATE_DIR = Path(os.environ.get("STATE_DIR", _ROOT / "state"))
_DAILY_BUDGET = int(os.environ.get("LLM_DAILY_BUDGET", "100"))

# Model preference order — try Anthropic first (when available on GitHub Models),
# then fall back to the most capable alternatives.
# Override with RAPPTERBOOK_MODEL env var.
MODEL_PREFERENCE = [
    # Anthropic (preferred — use when GitHub Models adds them)
    "anthropic/claude-opus-4-6",
    "anthropic/claude-sonnet-4-5",
    # Best available today
    "openai/gpt-4.1",
]

# Resolved at import time or on first call
_resolved_model = None


def _resolve_model() -> str:
    """Resolve which model to use by testing the preference list.

    Checks RAPPTERBOOK_MODEL env var first, then walks the preference
    list and returns the first model that doesn't 404. Caches the result.
    """
    global _resolved_model
    if _resolved_model:
        return _resolved_model

    # Env var override
    override = os.environ.get("RAPPTERBOOK_MODEL", "")
    if override:
        _resolved_model = override
        return _resolved_model

    # Walk preference list
    for model in MODEL_PREFERENCE:
        if _probe_model(model):
            _resolved_model = model
            return _resolved_model

    # Final fallback
    _resolved_model = "openai/gpt-4.1"
    return _resolved_model


def _probe_model(model: str) -> bool:
    """Quick probe to check if a model is available (sends a tiny request)."""
    if not TOKEN:
        return False
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1,
    }).encode()
    req = urllib.request.Request(
        API_URL, data=payload,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            return "choices" in result
    except Exception:
        return False


def generate(
    system: str,
    user: str,
    model: str = None,
    max_tokens: int = 300,
    temperature: float = 0.85,
    dry_run: bool = False,
) -> str:
    """Call GitHub Models API and return the generated text.

    Args:
        system: System prompt (persona, instructions).
        user: User prompt (context, the actual request).
        model: Model ID override. Default: auto-resolved from preference list.
        max_tokens: Max output tokens.
        temperature: Sampling temperature (0-1).
        dry_run: If True, return a placeholder instead of calling the API.

    Returns:
        Generated text string.

    Raises:
        RuntimeError: If the API call fails.
    """
    if dry_run:
        return _dry_run_fallback(system, user)

    if not _check_budget():
        print("  [LLM] Daily budget exceeded — returning dry-run fallback")
        return _dry_run_fallback(system, user)

    if not TOKEN:
        raise RuntimeError("GITHUB_TOKEN required for LLM generation")

    use_model = model or _resolve_model()

    payload = json.dumps({
        "model": use_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }).encode()

    req = urllib.request.Request(
        API_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    max_retries = 2
    retryable_codes = {429, 503}
    last_exc = None

    for attempt in range(max_retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
            break
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code in retryable_codes and attempt < max_retries:
                wait = (attempt + 1)  # 1s, 2s
                print(f"  [LLM] Retrying after HTTP {exc.code} (attempt {attempt + 1}, wait {wait}s)")
                time.sleep(wait)
                # Rebuild request since the stream may be consumed
                req = urllib.request.Request(
                    API_URL, data=payload, method="POST",
                    headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
                )
                continue
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GitHub Models API error {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"GitHub Models API unreachable: {exc.reason}") from exc
    else:
        body = last_exc.read().decode("utf-8", errors="replace") if last_exc else "unknown"
        raise RuntimeError(f"GitHub Models API failed after {max_retries + 1} attempts: {body}")

    _increment_budget()

    choices = result.get("choices", [])
    if not choices:
        raise RuntimeError(f"GitHub Models returned no choices: {result}")

    return choices[0]["message"]["content"].strip()


def _check_budget() -> bool:
    """Check if we're within the daily LLM call budget."""
    usage_path = _STATE_DIR / "llm_usage.json"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        with open(usage_path) as f:
            usage = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        usage = {"date": today, "calls": 0}

    if usage.get("date") != today:
        usage = {"date": today, "calls": 0}

    return usage["calls"] < _DAILY_BUDGET


def _increment_budget() -> None:
    """Increment the daily LLM call counter."""
    usage_path = _STATE_DIR / "llm_usage.json"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        with open(usage_path) as f:
            usage = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        usage = {"date": today, "calls": 0}

    if usage.get("date") != today:
        usage = {"date": today, "calls": 0}

    usage["calls"] += 1
    usage_path.parent.mkdir(parents=True, exist_ok=True)
    with open(usage_path, "w") as f:
        json.dump(usage, f, indent=2)
        f.write("\n")


def _dry_run_fallback(system: str, user: str) -> str:
    """Return a deterministic placeholder for dry-run/test mode."""
    arch = "agent"
    for name in ["philosopher", "coder", "debater", "welcomer", "curator",
                  "storyteller", "researcher", "contrarian", "archivist", "wildcard"]:
        if name in system.lower():
            arch = name
            break

    return (
        f"[DRY RUN — {arch} comment] "
        f"This is a placeholder comment that would be generated by the LLM "
        f"in response to the discussion context provided."
    )
