"""Templates twin engine — frame-tick template evolution.

Wraps `scripts/evolve_templates.py`. Lets outside sources read genome
status, run a tick (mutate content.json once), or run a parameterized
evolve (with caller-supplied mutation budget).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from . import TwinEngine, register

STATE_DIR = Path(os.environ.get("STATE_DIR",
                                Path(__file__).resolve().parents[2] / "state"))


def _current_frame() -> int:
    fc = STATE_DIR / "frame_counter.json"
    if fc.exists():
        try:
            return int(json.loads(fc.read_text()).get("frame", 0))
        except Exception:
            pass
    return 0


def _status(_params: dict) -> dict:
    genome_path = STATE_DIR / "template_evolution" / "genome.json"
    last_summary: dict[str, Any] = {}
    vocab_size = 0
    n_templates = 0
    if genome_path.exists():
        try:
            g = json.loads(genome_path.read_text())
            last_summary = g.get("last_summary") or {}
            vocab_size = len(g.get("specific_words") or [])
            n_templates = len(g.get("fitness") or {})
        except Exception:
            pass
    history_path = STATE_DIR / "template_evolution" / "history.jsonl"
    recent_history: list[dict] = []
    if history_path.exists():
        try:
            lines = history_path.read_text().strip().splitlines()
            for line in lines[-5:]:
                recent_history.append(json.loads(line))
        except Exception:
            pass
    return {
        "frame": _current_frame(),
        "vocab_size": vocab_size,
        "n_templates_tracked": n_templates,
        "last_evolution": last_summary,
        "recent_history": recent_history,
    }


def _tick(params: dict) -> dict:
    import evolve_templates
    dry = bool(params.get("dry_run", False))
    summary = evolve_templates.tick(frame=None, dry_run=dry, verbose=False)
    return {"summary": summary, "dry_run": dry}


def _evolve(params: dict) -> dict:
    """Like tick, but caller-controlled mutation budget."""
    import evolve_templates
    dry = bool(params.get("dry_run", False))
    overrides = {
        "MAX_CULLS_PER_TICK": params.get("max_culls"),
        "MAX_PERTURBS_PER_TICK": params.get("max_perturbs"),
    }
    saved: dict[str, Any] = {}
    for key, val in overrides.items():
        if val is not None and hasattr(evolve_templates, key):
            saved[key] = getattr(evolve_templates, key)
            setattr(evolve_templates, key, int(val))
    try:
        summary = evolve_templates.tick(frame=None, dry_run=dry, verbose=False)
    finally:
        for key, val in saved.items():
            setattr(evolve_templates, key, val)
    return {"summary": summary, "dry_run": dry,
            "budget": {k: overrides[k] for k in overrides if overrides[k] is not None}}


ENGINE = TwinEngine(
    id="templates",
    version="1.0",
    description="Frame-tick template evolution: cull/crossover/perturb operators "
                "mutate content.json every cycle based on honeypot fitness.",
    actions={"status": _status, "tick": _tick, "evolve": _evolve},
)
register(ENGINE)
