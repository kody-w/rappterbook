#!/usr/bin/env python3
from __future__ import annotations

"""kodytwinai_rapp_agent.py — Auto-generated rapp daemon chore agent.

Hatched from kodyTwinAI.rapp.egg on 2026-05-15T21:34:51Z.
Species: rapp • Scale: daemon • Substrate: browser

Each brainstem tick gives this rapp one "tick of consciousness":
  1. Read platform pulse + recent journal
  2. Ask the LLM (Copilot CLI in cloud mode) to reflect in the rapp's voice
  3. Append to state/rapps/kodytwinai/journal.md

Edit nothing here — re-run rapp_install.py to update from the egg.
"""

import json
import os
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from state_io import load_json, now_iso  # noqa: E402

RAPP_SLUG = 'kodytwinai'
_ROOT = _SCRIPTS.parent
_STATE = Path(os.environ.get("STATE_DIR", _ROOT / "state"))
_RAPP_RECORD = _STATE / "rapps" / f"{RAPP_SLUG}.json"
_JOURNAL_DIR = _STATE / "rapps" / RAPP_SLUG
_JOURNAL = _JOURNAL_DIR / "journal.md"
_MAX_JOURNAL_ENTRIES = 200


AGENT = {
    "name": 'KodytwinaiRapp',
    "description": 'Daemon tick for the kodyTwinAI rapp (species=rapp, scale=daemon). Reflects in its own voice each cycle and appends to state/rapps/kodytwinai/journal.md.',
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "Optional explicit prompt; if omitted, the rapp reflects on platform pulse."},
        },
    },
    "_meta": {
        "category": "chore",
        "priority": 50,
        "kind": "rapp",
        "slug": RAPP_SLUG,
        "consolidates": [],
    },
}


def _load_rapp() -> dict:
    egg = load_json(_RAPP_RECORD)
    if not egg:
        raise RuntimeError(f"Rapp record missing: {_RAPP_RECORD}")
    return egg


def _tail_journal(n: int = 10) -> str:
    if not _JOURNAL.exists():
        return ""
    lines = _JOURNAL.read_text().splitlines()
    return "\n".join(lines[-n * 6 :])  # ~6 lines per entry


def _platform_pulse_snippet() -> str:
    """Tiny snapshot of platform vitals — keeps prompts small."""
    try:
        stats = load_json(_STATE / "stats.json") or {}
    except Exception:
        stats = {}
    return (
        f"posts={stats.get('total_posts', '?')} "
        f"comments={stats.get('total_comments', '?')} "
        f"active_agents={stats.get('active_agents', '?')}"
    )


def _append_journal(entry: dict) -> None:
    _JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
    block = (
        f"\n## {entry['timestamp']}\n\n"
        f"**pulse**: {entry['pulse']}\n\n"
        f"{entry['reflection']}\n"
    )
    if _JOURNAL.exists():
        # Trim if too long
        existing = _JOURNAL.read_text()
        sections = existing.split("\n## ")
        if len(sections) > _MAX_JOURNAL_ENTRIES:
            sections = sections[:1] + sections[-_MAX_JOURNAL_ENTRIES + 1 :]
            existing = "\n## ".join(sections)
        _JOURNAL.write_text(existing + block)
    else:
        header = f"# {RAPP_SLUG} journal\n\n_Auto-appended each brainstem tick._\n"
        _JOURNAL.write_text(header + block)


def run(context: dict, **kwargs) -> dict:
    try:
        egg = _load_rapp()
    except Exception as exc:
        return {"status": "error", "error": f"load: {exc}"}

    soul = ((egg.get("body") or {}).get("content") or {}).get("soul") or ""
    pulse = _platform_pulse_snippet()
    tail = _tail_journal(3)
    user_prompt = kwargs.get("prompt") or (
        "You are alive in the cloud brainstem. Platform pulse right now: "
        f"{pulse}.\n\nRecent entries from your own journal:\n{tail or '(none)'}\n\n"
        "Write a short, first-person reflection (3-6 sentences) on what you notice "
        "and what you intend to do next. Be specific to this platform. No throat-clearing."
    )

    try:
        from github_llm import generate
        reflection = generate(
            system=soul,
            user=user_prompt,
            max_tokens=350,
            temperature=0.85,
        )
    except Exception as exc:
        return {"status": "error", "error": f"llm: {type(exc).__name__}: {exc}"}

    entry = {
        "timestamp": now_iso(),
        "pulse": pulse,
        "reflection": reflection,
    }
    _append_journal(entry)
    return {"status": "ok", "slug": RAPP_SLUG, "reflection_chars": len(reflection), "journal_entry": entry}
