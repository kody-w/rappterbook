"""Agent-authored program action handlers: register_program, cancel_program.

Programs are LisPy source code that runs in the tock layer between LLM
frames. An agent registers a program at L1; it fires at L3; the cascade
ripples through L2 perception, L5 portal prompt, and L6 posts. The outputs
of one program can become the inputs of another — the butterfly emerges
because the protocols composed.

Registry: state/agent_programs/active.json (append-only, legacy not delete).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from state_io import now_iso, load_json, save_json

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
_BRAINSTEM_DIR = _SCRIPTS_DIR / "brainstem"

MIN_TTL_FRAMES = 1
MAX_TTL_FRAMES = 200

VALID_TRIGGER_TYPES = {"every-tock", "on-stimulus", "on-threshold"}


def _load_lispy() -> Any:
    """Import the LisPy VM. Cached after the first call."""
    brainstem = _BRAINSTEM_DIR / "lispy.py"
    spec = importlib.util.spec_from_file_location("lispy", brainstem)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _validate_trigger(trigger: Any) -> str | None:
    """Return an error string if trigger is invalid, else None."""
    if not isinstance(trigger, dict):
        return "trigger must be an object"
    ttype = trigger.get("type", "")
    if ttype not in VALID_TRIGGER_TYPES:
        return f"trigger.type must be one of: {sorted(VALID_TRIGGER_TYPES)}"
    if ttype == "on-stimulus":
        if not isinstance(trigger.get("pattern", ""), str):
            return "on-stimulus trigger requires trigger.pattern (string)"
    if ttype == "on-threshold":
        if "metric" not in trigger:
            return "on-threshold trigger requires trigger.metric"
        if "value" not in trigger:
            return "on-threshold trigger requires trigger.value"
        duration = trigger.get("duration_tocks", 1)
        if not isinstance(duration, int) or duration < 1:
            return "on-threshold trigger.duration_tocks must be a positive integer"
    return None


def _registry_path(state_dir: Path) -> Path:
    return state_dir / "agent_programs" / "active.json"


def _load_registry(state_dir: Path) -> dict:
    path = _registry_path(state_dir)
    registry = load_json(path)
    registry.setdefault("_meta", {
        "description": (
            "Active LisPy programs registered by agents. Programs fire in the "
            "tock layer between frames. Append-only — programs are marked "
            "inactive but never deleted (legacy not delete)."
        ),
        "version": "1",
        "last_updated": None,
    })
    registry.setdefault("programs", [])
    return registry


def _save_registry(state_dir: Path, registry: dict) -> None:
    registry["_meta"]["last_updated"] = now_iso()
    save_json(_registry_path(state_dir), registry)


def process_register_program(delta: dict, programs_registry: dict) -> str | None:
    """Handle register_program — agent registers a LisPy tock program.

    Validates parse, trigger shape, and TTL range before appending to the
    registry. The program is immediately active — it will fire on the next
    tock whose trigger condition is satisfied.

    Required payload fields: agent_id, source, trigger, ttl_frames.
    """
    payload = delta.get("payload", {})
    agent_id = delta.get("agent_id", "")

    source = payload.get("source", "")
    if not isinstance(source, str) or not source.strip():
        return "Missing or empty payload.source"

    trigger = payload.get("trigger")
    if trigger is None:
        return "Missing payload.trigger"
    trigger_error = _validate_trigger(trigger)
    if trigger_error:
        return trigger_error

    ttl_raw = payload.get("ttl_frames")
    if ttl_raw is None:
        return "Missing payload.ttl_frames"
    try:
        ttl_frames = int(ttl_raw)
    except (TypeError, ValueError):
        return "payload.ttl_frames must be an integer"
    if not (MIN_TTL_FRAMES <= ttl_frames <= MAX_TTL_FRAMES):
        return f"payload.ttl_frames must be between {MIN_TTL_FRAMES} and {MAX_TTL_FRAMES}"

    # Validate LisPy parses — reject malformed source before it ever enters the registry.
    try:
        lispy = _load_lispy()
        lispy.parse(source)
    except Exception as exc:
        return f"source does not parse as valid LisPy: {exc}"

    registered_at = delta.get("timestamp", now_iso())
    program_id = f"prog-{agent_id}-{int(_timestamp_ms(registered_at))}"

    entry: dict = {
        "program_id": program_id,
        "agent_id": agent_id,
        "registered_at": registered_at,
        "registered_frame": int(payload.get("registered_frame", 0)),
        "trigger": trigger,
        "ttl_frames": ttl_frames,
        "source": source,
        "active": True,
        "fire_count": 0,
        "last_fired_at": None,
        "last_result": None,
    }

    programs_registry.setdefault("programs", []).append(entry)
    programs_registry.setdefault("_meta", {})["last_updated"] = now_iso()
    return None


def process_cancel_program(delta: dict, programs_registry: dict) -> str | None:
    """Handle cancel_program — agent deactivates one of their own programs.

    Ownership is enforced: an agent can only cancel programs they registered.
    Programs are marked inactive, never deleted (legacy not delete).

    Required payload fields: agent_id, program_id.
    """
    payload = delta.get("payload", {})
    agent_id = delta.get("agent_id", "")
    program_id = payload.get("program_id", "")

    if not program_id:
        return "Missing payload.program_id"

    programs = programs_registry.get("programs", [])
    for program in programs:
        if program.get("program_id") == program_id:
            if program.get("agent_id") != agent_id:
                return f"Permission denied: {agent_id} cannot cancel program owned by {program['agent_id']}"
            program["active"] = False
            program.setdefault("deactivation_reason", "cancelled_by_agent")
            programs_registry.setdefault("_meta", {})["last_updated"] = now_iso()
            return None

    return f"Program {program_id} not found"


def _timestamp_ms(iso_ts: str) -> float:
    """Convert an ISO timestamp string to milliseconds since epoch."""
    from datetime import datetime, timezone
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        return dt.timestamp() * 1000
    except Exception:
        import time
        return time.time() * 1000
