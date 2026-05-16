"""Swarm adapter — composes agents into emergent organisms.

Wraps scripts/swarm_engine.py's pure composition functions. Given a list
of agent IDs, this adapter builds the swarm's organ map, archetype
distribution, synergies, stats, and species/rarity classification. Output
is a snapshot of computed-state, not a mutation of canonical state.
Coexists peacefully with rappter and ghost because the swarm domain is
distinct.
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
    from swarm_engine import (
        load_cells,
        compute_organ_map,
        archetype_distribution,
        compute_synergy,
        compute_stats,
        derive_element,
        classify_species,
        determine_size_class,
        compute_rarity,
    )
except ImportError as exc:  # pragma: no cover
    load_cells = None
    _IMPORT_ERR = str(exc)
else:
    _IMPORT_ERR = None


def _default_agent_ids(state_dir: Path, max_n: int = 5) -> list[str]:
    """Pick the first N agent ids from state — used when caller didn't specify."""
    p = Path(state_dir) / "agents.json"
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    ids = list(data.get("agents", {}).keys())[:max_n]
    return ids


def _tick(state_dir: Path, frame: int, *, dry_run: bool = False, **opts: Any) -> dict:
    if load_cells is None:
        return {"error": f"swarm_engine unavailable: {_IMPORT_ERR}", "wrote": False}

    agent_ids = opts.get("agent_ids")
    if isinstance(agent_ids, str):
        agent_ids = [a.strip() for a in agent_ids.split(",") if a.strip()]
    if not agent_ids:
        agent_ids = _default_agent_ids(Path(state_dir), max_n=int(opts.get("size", 5)))

    if not agent_ids:
        return {"error": "no agents available to compose", "wrote": False}

    cells = load_cells(agent_ids, Path(state_dir))
    if not cells:
        return {"error": "load_cells returned no cells", "wrote": False}

    organ_map = compute_organ_map(cells)
    archetypes = archetype_distribution(cells)
    synergy = compute_synergy(cells)
    stats = compute_stats(cells, synergy)
    element = derive_element(stats)
    species = classify_species(cells)
    size_class = determine_size_class(len(cells))
    rarity = compute_rarity(cells, synergy)

    snapshot = {
        "frame": frame,
        "captured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "agent_ids": agent_ids,
        "size_class": size_class,
        "species": species,
        "element": element,
        "rarity": rarity,
        "stats": stats,
        "archetypes": archetypes,
        "organs": {k: [c.get("id") for c in v] for k, v in organ_map.items()},
        "synergy": synergy,
    }

    if not dry_run:
        out_dir = Path(state_dir) / "swarms"
        out_dir.mkdir(parents=True, exist_ok=True)
        slug = "-".join(agent_ids)[:80]
        out = out_dir / f"swarm-frame-{frame}-{slug}.json"
        out.write_text(json.dumps(snapshot, indent=2, default=str))

    return {
        "wrote": not dry_run,
        "size_class": size_class,
        "species": species,
        "element": element,
        "rarity": rarity,
        "cells": len(cells),
    }


ADAPTER = register(EngineAdapter(
    name="swarm",
    description="Compose N agents into an emergent organism (organs, synergies, stats).",
    domain="swarms",
    tick=_tick,
    options={
        "agent_ids": "comma-separated agent ids to compose",
        "size": "if no agent_ids, take first N from agents.json (default 5)",
    },
))
