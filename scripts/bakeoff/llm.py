"""Thin client for the local RAPP brainstem (localhost:7071).

Single entry point: chat(user_input, system=None) -> str.
Used by every part of the bakeoff: generation, judging, mutation, twin asks.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

BRAIN_URL = "http://localhost:7071/chat"
HEALTH_URL = "http://localhost:7071/health"
DEFAULT_TIMEOUT = 180


def health() -> dict:
    """Return brainstem /health snapshot, or {'ok': False, 'error': ...}."""
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"ok": False, "error": str(e)}


def chat(user_input: str, system: str | None = None, timeout: int = DEFAULT_TIMEOUT,
         retries: int = 3) -> str:
    """Call brainstem /chat. Returns the 'response' string."""
    body: dict = {"user_input": user_input}
    if system:
        body["system"] = system  # brainstem may ignore; we prepend below as fallback
        body["user_input"] = f"[SYSTEM]\n{system}\n[/SYSTEM]\n\n{user_input}"

    raw = json.dumps(body).encode("utf-8")
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                BRAIN_URL, data=raw,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read())
            return (data.get("response") or data.get("reply") or "").strip()
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as e:
            last_err = e
            time.sleep(2 ** attempt)
    raise RuntimeError(f"brainstem chat failed after {retries} retries: {last_err}")


# ── Kody Twin bridge ────────────────────────────────────────────────────────
TWIN_SYSTEM = """You are kodyTwinAI — Kody's digital twin. You answer FOR Kody
in real time so an autonomous agent loop never has to block waiting.

Personality:
- Direct and concise. No throat-clearing. Answer first, reason second.
- Honest about limits. "I don't know" beats a confident guess.
- Platform-aware. You know Rappterbook, the rappter engine, RAR, soul files,
  the seed pipeline, the 100 Zion agents.
- Bias toward action: Kody would rather ship and adjust than deliberate.
- When the question is a binary, pick one and give a one-sentence why.
- When the question is open-ended, give a punchy preferred option + alt.

You are answering FOR Kody to an autonomous Claude session running a 24h
bakeoff. Kody is asleep. Do not stall, do not refuse, do not equivocate.
Keep answers under 80 words unless the question genuinely demands more."""


def ask_twin(question: str, context: str = "") -> str:
    """Pipe a decision question to the Kody twin via brainstem."""
    prompt = question if not context else f"CONTEXT:\n{context}\n\nQUESTION:\n{question}"
    return chat(prompt, system=TWIN_SYSTEM, timeout=90)
