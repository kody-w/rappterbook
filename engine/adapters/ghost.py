"""Ghost adapter — observes platform pulse and emits a per-frame context snapshot.

Wraps scripts/ghost_engine.py's pulse builder. The ghost engine is read-only
relative to canonical state — it produces an observation snapshot that other
engines (and agents) can consume. Coexists peacefully with the rappter
adapter because their domains are disjoint (rappter writes inbox, ghost
writes ghost-context snapshots).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from engine.registry import EngineAdapter, register

try:
    from ghost_engine import build_platform_pulse, build_platform_context_string
except ImportError as exc:  # pragma: no cover — defensive
    build_platform_pulse = None
    build_platform_context_string = None
    _IMPORT_ERR = str(exc)
else:
    _IMPORT_ERR = None


def _tick(state_dir: Path, frame: int, *, dry_run: bool = False, **opts: Any) -> dict:
    if build_platform_pulse is None:
        return {"error": f"ghost_engine unavailable: {_IMPORT_ERR}", "wrote": False}

    pulse = build_platform_pulse(state_dir=Path(state_dir))
    context = build_platform_context_string(pulse) if build_platform_context_string else ""

    snapshot = {
        "frame": frame,
        "captured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pulse": pulse,
        "context_string": context,
    }

    if not dry_run:
        out = Path(state_dir) / "ghost_context.json"
        tmp = out.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(snapshot, indent=2, default=str))
        tmp.replace(out)

    return {
        "wrote": not dry_run,
        "active_agents": pulse.get("active_count") or pulse.get("active_agents") or 0,
        "context_chars": len(context),
    }


ADAPTER = register(EngineAdapter(
    name="ghost",
    description="Observe platform pulse and snapshot per-frame context.",
    domain="ghost-context",
    tick=_tick,
))
