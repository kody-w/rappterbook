#!/usr/bin/env python3
from __future__ import annotations

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
import fcntl
import json
import os
import subprocess
import time
import urllib.request
import urllib.error

from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timezone


class LLMRateLimitError(RuntimeError):
    """Raised when the LLM circuit breaker trips due to sustained 429s.

    Callers should catch this to distinguish rate-limit exhaustion from
    other LLM failures, enabling accurate reporting and early termination.
    """
    pass


class ContentFilterError(RuntimeError):
    """Raised when the LLM rejects a prompt due to content filtering.

    Callers can catch this to retry with a softened prompt instead of
    failing silently.
    """
    pass


# ── Circuit breaker (module-level) ───────────────────────────────────
# Trips after consecutive 429s to avoid hammering a rate-limited backend.
_circuit_breaker = {"consecutive_429s": 0, "tripped_until": 0.0}
_CIRCUIT_BREAKER_THRESHOLD = 3    # trip after 3 consecutive 429s
_CIRCUIT_BREAKER_COOLDOWN = 300   # 5-minute cooldown when tripped

# ── Backend configuration ────────────────────────────────────────────

# Azure OpenAI
AZURE_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
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

# ── Faster backoff schedule (seconds) ───────────────────────────────
_BACKOFF_SCHEDULE = [1, 3, 9, 27]


# ── Budget file lock (self-contained, no state_io coupling) ─────────

@contextmanager
def _budget_lock():
    """Advisory file lock for the LLM usage file.

    Same pattern as state_io._file_lock but self-contained to avoid
    circular imports. Falls through on timeout (never blocks forever).
    """
    lock_path = _STATE_DIR / "llm_usage.json.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = None
    try:
        lock_fd = open(lock_path, "w")
        deadline = time.time() + 5.0
        while True:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (OSError, IOError):
                if time.time() >= deadline:
                    break  # proceed without lock
                time.sleep(0.05)
        yield
    finally:
        if lock_fd:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                lock_fd.close()
            except Exception:
                pass


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
                wait = min(int(retry_after), 120) if retry_after.isdigit() else _BACKOFF_SCHEDULE[min(attempt, len(_BACKOFF_SCHEDULE) - 1)]
                print(f"  [AZURE] Retrying after HTTP {exc.code} (attempt {attempt + 1}, wait {wait}s)")
                time.sleep(wait)
                continue
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code == 400 and "filtered" in body.lower():
                raise ContentFilterError(
                    f"Prompt rejected by content filter: {body[:200]}"
                ) from exc
            raise RuntimeError(f"Azure OpenAI error {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Azure OpenAI unreachable: {exc.reason}") from exc

    body = last_exc.read().decode("utf-8", errors="replace") if last_exc else "unknown"
    raise RuntimeError(f"Azure OpenAI failed after {max_retries + 1} attempts: {body}")


# ── GitHub Models backend ─────────────────────────────────────────────

def _resolve_model() -> str:
    """Resolve which GitHub Models model to use.

    Checks an on-disk cache (< 1 hour old) before probing the API,
    so repeated calls within a session skip the network round-trip.
    """
    global _resolved_model
    if _resolved_model:
        return _resolved_model

    override = os.environ.get("RAPPTERBOOK_MODEL", "")
    if override:
        _resolved_model = override
        return _resolved_model

    # Check disk cache
    cache_path = _STATE_DIR / ".model_cache.json"
    try:
        with open(cache_path) as f:
            cache = json.load(f)
        cached_ts = cache.get("timestamp", 0)
        cached_model = cache.get("model", "")
        if cached_model and (time.time() - cached_ts) < 3600:
            _resolved_model = cached_model
            return _resolved_model
    except Exception:
        pass  # cache miss or corrupt — fall through to probe

    for model in MODEL_PREFERENCE:
        if _probe_model(model):
            _resolved_model = model
            # Write cache
            try:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                with open(cache_path, "w") as f:
                    json.dump({"model": model, "timestamp": time.time()}, f)
            except Exception:
                pass  # non-fatal
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
        raise LLMRateLimitError(
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
            with urllib.request.urlopen(req, timeout=60) as resp:
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
                wait = min(int(retry_after), 120) if retry_after.isdigit() else _BACKOFF_SCHEDULE[min(attempt, len(_BACKOFF_SCHEDULE) - 1)]
                print(f"  [LLM] Retrying after HTTP {exc.code} (attempt {attempt + 1}, wait {wait}s)")
                time.sleep(wait)
                continue
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code == 400 and "filtered" in body.lower():
                raise ContentFilterError(
                    f"Prompt rejected by content filter: {body[:200]}"
                ) from exc
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
        except ContentFilterError:
            raise  # Propagate content filter errors immediately
        except Exception as exc:
            errors.append(f"Azure: {exc}")
            print(f"  [AZURE] Failed, falling back to GitHub Models: {exc}")

    # Backend 2: GitHub Models
    if GITHUB_TOKEN:
        try:
            result = _generate_github(system, user, model, max_tokens, temperature)
            _increment_budget()
            return result
        except (LLMRateLimitError, ContentFilterError):
            raise  # Propagate rate limit and content filter errors immediately
        except Exception as exc:
            errors.append(f"GitHub: {exc}")

    # Backend 3: Copilot CLI (separate rate limit pool)
    try:
        result = _generate_copilot(system, user, max_tokens, temperature)
        _increment_budget()
        return result
    except Exception as exc:
        errors.append(f"Copilot: {exc}")

    raise RuntimeError(f"All LLM backends failed: {'; '.join(errors)}")


# ── Function calling API ──────────────────────────────────────────────

class _ToolResponse:
    """Lightweight response wrapper for generate_with_tools()."""
    __slots__ = ("content", "function_call", "raw")

    def __init__(self, content="", function_call=None, raw=None):
        self.content = content
        self.function_call = function_call
        self.raw = raw or {}


def _generate_github_with_tools(
    messages: list,
    tools: list | None = None,
    model: str = None,
    max_tokens: int = 800,
    temperature: float = 0.85,
) -> _ToolResponse:
    """Call GitHub Models API with function/tool calling support.

    Uses the OpenAI-compatible chat completions endpoint with tools.
    Returns a _ToolResponse with either content or function_call.
    """
    if not GITHUB_TOKEN:
        raise RuntimeError("GITHUB_TOKEN required for GitHub Models")

    use_model = model or _resolve_model()

    payload = {
        "model": use_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    data = json.dumps(payload).encode()

    # Check circuit breaker
    if time.time() < _circuit_breaker["tripped_until"]:
        remaining = int(_circuit_breaker["tripped_until"] - time.time())
        raise LLMRateLimitError(
            f"Circuit breaker tripped — cooling down for {remaining}s more."
        )

    max_retries = 4
    retryable_codes = {429, 502, 503}
    last_exc = None
    result = None

    for attempt in range(max_retries + 1):
        req = urllib.request.Request(
            GITHUB_API_URL,
            data=data,
            headers={
                "Authorization": f"Bearer {GITHUB_TOKEN}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                result = json.loads(resp.read())
            _circuit_breaker["consecutive_429s"] = 0
            break
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code == 429:
                _circuit_breaker["consecutive_429s"] += 1
                if _circuit_breaker["consecutive_429s"] >= _CIRCUIT_BREAKER_THRESHOLD:
                    _circuit_breaker["tripped_until"] = time.time() + _CIRCUIT_BREAKER_COOLDOWN
            if exc.code in retryable_codes and attempt < max_retries:
                retry_after = exc.headers.get("Retry-After", "") if exc.headers else ""
                wait = min(int(retry_after), 120) if retry_after.isdigit() else _BACKOFF_SCHEDULE[min(attempt, len(_BACKOFF_SCHEDULE) - 1)]
                print(f"  [LLM-TOOLS] Retrying after HTTP {exc.code} (attempt {attempt + 1}, wait {wait}s)")
                time.sleep(wait)
                continue
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code == 400 and "filtered" in body.lower():
                raise ContentFilterError(f"Prompt rejected by content filter: {body[:200]}") from exc
            raise RuntimeError(f"GitHub Models API error {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"GitHub Models API unreachable: {exc.reason}") from exc
    else:
        body = last_exc.read().decode("utf-8", errors="replace") if last_exc else "unknown"
        raise RuntimeError(f"GitHub Models API failed after {max_retries + 1} attempts: {body}")

    choices = result.get("choices", [])
    if not choices:
        raise RuntimeError(f"GitHub Models returned no choices: {result}")

    message = choices[0].get("message", {})
    content = message.get("content", "") or ""

    # Check for tool calls (OpenAI format)
    tool_calls = message.get("tool_calls", [])
    if tool_calls:
        tc = tool_calls[0]  # Take the first tool call
        fn = tc.get("function", {})
        return _ToolResponse(
            content=content.strip(),
            function_call={
                "name": fn.get("name", ""),
                "arguments": fn.get("arguments", "{}"),
            },
            raw=result,
        )

    # Legacy function_call format
    fc = message.get("function_call")
    if fc:
        return _ToolResponse(
            content=content.strip(),
            function_call={
                "name": fc.get("name", ""),
                "arguments": fc.get("arguments", "{}"),
            },
            raw=result,
        )

    return _ToolResponse(content=content.strip(), raw=result)


def generate_with_tools(
    messages: list,
    tools: list | None = None,
    model: str = None,
    max_tokens: int = 800,
    temperature: float = 0.85,
    dry_run: bool = False,
) -> _ToolResponse:
    """Generate a response with optional function/tool calling.

    Uses GitHub Models API (OpenAI-compatible) with tools parameter.
    Budget-limited. Falls back gracefully.

    Args:
        messages: Chat messages in OpenAI format.
        tools: Tool definitions in OpenAI format, or None.
        model: Model ID override.
        max_tokens: Max output tokens.
        temperature: Sampling temperature.
        dry_run: If True, return a placeholder response.

    Returns:
        _ToolResponse with .content and/or .function_call
    """
    if dry_run:
        return _ToolResponse(content="[DRY RUN] Tool-calling response placeholder")

    if not _check_budget():
        print("  [LLM] Daily budget exceeded — returning dry-run fallback")
        return _ToolResponse(content="[BUDGET] Daily LLM budget exceeded")

    errors = []

    # GitHub Models is the primary backend for tool calling
    if GITHUB_TOKEN:
        try:
            result = _generate_github_with_tools(
                messages, tools, model, max_tokens, temperature
            )
            _increment_budget()
            return result
        except (LLMRateLimitError, ContentFilterError):
            raise
        except Exception as exc:
            errors.append(f"GitHub: {exc}")
            print(f"  [LLM-TOOLS] GitHub Models failed: {exc}")

    # Fallback: strip tools and use basic generate()
    # (tool calling degrades to text-only)
    system_parts = []
    user_parts = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "") or ""
        if role == "system":
            system_parts.append(content)
        elif role in ("user", "function"):
            user_parts.append(content)

    if tools:
        tool_desc = "\n\nAvailable tools (output TOOL_CALL: <name> <json> to use):\n"
        for t in tools:
            fn = t.get("function", {})
            tool_desc += f"- {fn.get('name', '?')}: {fn.get('description', '')}\n"
        system_parts.append(tool_desc)

    try:
        text = generate(
            system="\n\n".join(system_parts),
            user="\n\n".join(user_parts),
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return _ToolResponse(content=text)
    except Exception as exc:
        errors.append(f"Fallback: {exc}")

    raise RuntimeError(f"All LLM backends failed for tool calling: {'; '.join(errors)}")


# ── Budget tracking ───────────────────────────────────────────────────

def _check_budget() -> bool:
    """Check if we're within the daily LLM call budget."""
    usage_path = _STATE_DIR / "llm_usage.json"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with _budget_lock():
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
    with _budget_lock():
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
