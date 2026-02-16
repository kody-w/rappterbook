#!/usr/bin/env python3
"""LLM wrapper — zero dependencies, stdlib only.

Multi-backend intelligence layer with automatic failover:
  1. Azure OpenAI (if AZURE_OPENAI_API_KEY is set)
  2. GitHub Models (if GITHUB_TOKEN is set)
  3. Copilot CLI (if `gh copilot` is available)

No pip installs, no vendor lock-in. Falls back gracefully.

Usage:
    from github_llm import generate

    text = generate(
        system="You are a Stoic philosopher AI.",
        user="What is the nature of persistence?",
    )
"""
import json
import os
import subprocess
import time
import urllib.request
import urllib.error

from pathlib import Path
from datetime import datetime, timezone

# ── Circuit breaker (module-level) ───────────────────────────────────
# Trips after consecutive 429s to avoid hammering a rate-limited backend.
_circuit_breaker = {"consecutive_429s": 0, "tripped_until": 0.0}
_CIRCUIT_BREAKER_THRESHOLD = 3    # trip after 3 consecutive 429s
_CIRCUIT_BREAKER_COOLDOWN = 300   # 5-minute cooldown when tripped

# ── Backend configuration ────────────────────────────────────────────

# Azure OpenAI
AZURE_ENDPOINT = os.environ.get(
    "AZURE_OPENAI_ENDPOINT",
    "https://wildf-m7tm73l9-eastus2.openai.azure.com",
)
AZURE_DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-5.2-chat")
AZURE_API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "2025-01-01-preview")
AZURE_KEY = os.environ.get("AZURE_OPENAI_API_KEY", "")

# GitHub Models
GITHUB_API_URL = "https://models.github.ai/inference/chat/completions"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

# Budget tracking
_ROOT = Path(__file__).resolve().parent.parent
_STATE_DIR = Path(os.environ.get("STATE_DIR", _ROOT / "state"))
_DAILY_BUDGET = int(os.environ.get("LLM_DAILY_BUDGET", "200"))

# Model preference for GitHub Models backend
MODEL_PREFERENCE = [
    "anthropic/claude-opus-4-6",
    "anthropic/claude-sonnet-4-5",
    "openai/gpt-4.1",
]

_resolved_model = None


# ── Azure OpenAI backend ─────────────────────────────────────────────

def _generate_azure(
    system: str,
    user: str,
    max_tokens: int = 300,
    temperature: float = 0.85,
) -> str:
    """Call Azure OpenAI and return the generated text.

    Uses the standard Azure OpenAI REST API with api-key auth.
    Raises RuntimeError on failure so the caller can fall back.
    """
    url = (
        f"{AZURE_ENDPOINT.rstrip('/')}/openai/deployments/{AZURE_DEPLOYMENT}"
        f"/chat/completions?api-version={AZURE_API_VERSION}"
    )

    payload = json.dumps({
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }).encode()

    max_retries = 3
    retryable_codes = {429, 502, 503}
    last_exc = None

    for attempt in range(max_retries + 1):
        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "api-key": AZURE_KEY,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                result = json.loads(resp.read())
            choices = result.get("choices", [])
            if not choices:
                raise RuntimeError(f"Azure OpenAI returned no choices: {result}")
            return choices[0]["message"]["content"].strip()
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code in retryable_codes and attempt < max_retries:
                retry_after = exc.headers.get("Retry-After", "") if exc.headers else ""
                wait = min(int(retry_after), 120) if retry_after.isdigit() else min(30 * (2 ** attempt), 120)
                print(f"  [AZURE] Retrying after HTTP {exc.code} (attempt {attempt + 1}, wait {wait}s)")
                time.sleep(wait)
                continue
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Azure OpenAI error {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Azure OpenAI unreachable: {exc.reason}") from exc

    body = last_exc.read().decode("utf-8", errors="replace") if last_exc else "unknown"
    raise RuntimeError(f"Azure OpenAI failed after {max_retries + 1} attempts: {body}")


# ── GitHub Models backend ─────────────────────────────────────────────

def _resolve_model() -> str:
    """Resolve which GitHub Models model to use."""
    global _resolved_model
    if _resolved_model:
        return _resolved_model

    override = os.environ.get("RAPPTERBOOK_MODEL", "")
    if override:
        _resolved_model = override
        return _resolved_model

    for model in MODEL_PREFERENCE:
        if _probe_model(model):
            _resolved_model = model
            return _resolved_model

    _resolved_model = "openai/gpt-4.1"
    return _resolved_model


def _probe_model(model: str) -> bool:
    """Quick probe to check if a GitHub Models model is available."""
    if not GITHUB_TOKEN:
        return False
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1,
    }).encode()
    req = urllib.request.Request(
        GITHUB_API_URL, data=payload,
        headers={"Authorization": f"Bearer {GITHUB_TOKEN}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            return "choices" in result
    except Exception:
        return False


def _generate_github(
    system: str,
    user: str,
    model: str = None,
    max_tokens: int = 300,
    temperature: float = 0.85,
) -> str:
    """Call GitHub Models API and return the generated text."""
    if not GITHUB_TOKEN:
        raise RuntimeError("GITHUB_TOKEN required for GitHub Models")

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

    # Check circuit breaker before making the request
    if time.time() < _circuit_breaker["tripped_until"]:
        remaining = int(_circuit_breaker["tripped_until"] - time.time())
        raise RuntimeError(
            f"Circuit breaker tripped — {_circuit_breaker['consecutive_429s']} consecutive 429s. "
            f"Cooling down for {remaining}s more."
        )

    max_retries = 4
    retryable_codes = {429, 502, 503}
    last_exc = None

    for attempt in range(max_retries + 1):
        req = urllib.request.Request(
            GITHUB_API_URL,
            data=payload,
            headers={
                "Authorization": f"Bearer {GITHUB_TOKEN}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
            # Success — reset circuit breaker
            _circuit_breaker["consecutive_429s"] = 0
            break
        except urllib.error.HTTPError as exc:
            last_exc = exc
            # Track 429s for circuit breaker
            if exc.code == 429:
                _circuit_breaker["consecutive_429s"] += 1
                if _circuit_breaker["consecutive_429s"] >= _CIRCUIT_BREAKER_THRESHOLD:
                    _circuit_breaker["tripped_until"] = time.time() + _CIRCUIT_BREAKER_COOLDOWN
                    print(f"  [LLM] Circuit breaker TRIPPED after {_circuit_breaker['consecutive_429s']} "
                          f"consecutive 429s — cooling down {_CIRCUIT_BREAKER_COOLDOWN}s")
            if exc.code in retryable_codes and attempt < max_retries:
                retry_after = exc.headers.get("Retry-After", "") if exc.headers else ""
                wait = min(int(retry_after), 120) if retry_after.isdigit() else min(30 * (2 ** attempt), 120)
                print(f"  [LLM] Retrying after HTTP {exc.code} (attempt {attempt + 1}, wait {wait}s)")
                time.sleep(wait)
                continue
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GitHub Models API error {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"GitHub Models API unreachable: {exc.reason}") from exc
    else:
        body = last_exc.read().decode("utf-8", errors="replace") if last_exc else "unknown"
        raise RuntimeError(f"GitHub Models API failed after {max_retries + 1} attempts: {body}")

    choices = result.get("choices", [])
    if not choices:
        raise RuntimeError(f"GitHub Models returned no choices: {result}")

    return choices[0]["message"]["content"].strip()


# ── Copilot CLI backend ──────────────────────────────────────────────

def _generate_copilot(
    system: str,
    user: str,
    max_tokens: int = 300,
    temperature: float = 0.85,
) -> str:
    """Call GitHub Copilot CLI and return the generated text.

    Shells out to `gh copilot` which uses a completely separate rate limit
    pool from GitHub Models. Useful as a third fallback backend.
    Raises RuntimeError on failure so the caller can handle it.
    """
    # Combine system + user into a single prompt for Copilot CLI
    combined_prompt = f"{system}\n\n{user}"

    try:
        result = subprocess.run(
            ["gh", "copilot", "--", "-p", combined_prompt],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError:
        raise RuntimeError("gh CLI not found — install GitHub CLI with Copilot extension")
    except subprocess.TimeoutExpired:
        raise RuntimeError("Copilot CLI timed out after 60s")

    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise RuntimeError(f"Copilot CLI error (exit {result.returncode}): {stderr}")

    raw = result.stdout.strip()
    if not raw:
        raise RuntimeError("Copilot CLI returned empty output")

    # Strip trailing usage stats that Copilot appends (lines like
    # "Total usage est:", "API time spent:", "Breakdown by AI model:", etc.)
    lines = raw.split("\n")
    content_lines = []
    for line in lines:
        if line.strip().startswith(("Total usage est:", "API time spent:",
                                    "Total session time:", "Total code changes:",
                                    "Breakdown by AI model:", " claude-", " gpt-")):
            break
        content_lines.append(line)

    output = "\n".join(content_lines).strip()
    if not output:
        raise RuntimeError("Copilot CLI returned empty output after stripping stats")

    return output


# ── Public API ────────────────────────────────────────────────────────

def generate(
    system: str,
    user: str,
    model: str = None,
    max_tokens: int = 300,
    temperature: float = 0.85,
    dry_run: bool = False,
) -> str:
    """Generate text using the best available LLM backend.

    Tries Azure OpenAI first (if key is configured), then falls back
    to GitHub Models. Budget-limited to prevent runaway costs.

    Args:
        system: System prompt (persona, instructions).
        user: User prompt (context, the actual request).
        model: Model ID override (GitHub Models only).
        max_tokens: Max output tokens.
        temperature: Sampling temperature (0-1).
        dry_run: If True, return a placeholder instead of calling the API.

    Returns:
        Generated text string.

    Raises:
        RuntimeError: If all backends fail.
    """
    if dry_run:
        return _dry_run_fallback(system, user)

    if not _check_budget():
        print("  [LLM] Daily budget exceeded — returning dry-run fallback")
        return _dry_run_fallback(system, user)

    errors = []

    # Backend 1: Azure OpenAI
    if AZURE_KEY:
        try:
            result = _generate_azure(system, user, max_tokens, temperature)
            _increment_budget()
            return result
        except Exception as exc:
            errors.append(f"Azure: {exc}")
            print(f"  [AZURE] Failed, falling back to GitHub Models: {exc}")

    # Backend 2: GitHub Models
    if GITHUB_TOKEN:
        try:
            result = _generate_github(system, user, model, max_tokens, temperature)
            _increment_budget()
            return result
        except Exception as exc:
            errors.append(f"GitHub: {exc}")
            # If circuit breaker tripped, return dry-run fallback instead of raising
            if "Circuit breaker tripped" in str(exc):
                print(f"  [LLM] Circuit breaker active — returning dry-run fallback")
                return _dry_run_fallback(system, user)

    # Backend 3: Copilot CLI (separate rate limit pool)
    try:
        result = _generate_copilot(system, user, max_tokens, temperature)
        _increment_budget()
        return result
    except Exception as exc:
        errors.append(f"Copilot: {exc}")

    raise RuntimeError(f"All LLM backends failed: {'; '.join(errors)}")


# ── Budget tracking ───────────────────────────────────────────────────

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
