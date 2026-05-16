"""Engine registry — coexistence layer for the engine twins.

Different engines do different things. The rappter twin drives agents on
the platform. The swarm engine composes agents into emergent organisms.
The ghost engine observes platform pulse to build per-agent context.
None of them replaces the others — they complement.

The registry gives each engine a uniform shape so they can run side by
side, be invoked by a single CLI, and be composed in a pulse loop. Each
adapter declares:

  * `name`         — short id used on the CLI (e.g. "rappter", "ghost")
  * `description`  — one-line summary
  * `domain`       — what slice of state it touches (e.g. "agents/inbox",
                     "swarms", "ghost-context"). Used to detect overlap.
  * `tick(state_dir, frame, *, dry_run=False, **opts) -> dict`
                   — run one tick, return a summary

Adapters MUST be safe to call with `dry_run=True` (no LLM, no GitHub).
Adapters MUST be safe to call when other adapters have already ticked
this frame — coexistence is the contract.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

TickFn = Callable[..., dict]


@dataclass
class EngineAdapter:
    name: str
    description: str
    domain: str
    tick: TickFn
    options: dict[str, str] = field(default_factory=dict)  # opt_name -> help text

    def run(self, state_dir: Path, frame: int, *, dry_run: bool = False, **opts: Any) -> dict:
        result = self.tick(state_dir, frame, dry_run=dry_run, **opts) or {}
        result.setdefault("engine", self.name)
        result.setdefault("frame", frame)
        return result


_REGISTRY: dict[str, EngineAdapter] = {}


def register(adapter: EngineAdapter) -> EngineAdapter:
    """Register an engine adapter. Re-registering the same name replaces."""
    _REGISTRY[adapter.name] = adapter
    return adapter


def get(name: str) -> EngineAdapter:
    if name not in _REGISTRY:
        raise KeyError(f"engine not registered: {name!r}. Known: {list(_REGISTRY)}")
    return _REGISTRY[name]


def all_engines() -> list[EngineAdapter]:
    return list(_REGISTRY.values())


def names() -> list[str]:
    return list(_REGISTRY.keys())


def domain_overlap() -> dict[str, list[str]]:
    """Return {domain: [engine_names]} for any domain claimed by >1 engine."""
    by_domain: dict[str, list[str]] = {}
    for adapter in _REGISTRY.values():
        by_domain.setdefault(adapter.domain, []).append(adapter.name)
    return {d: ns for d, ns in by_domain.items() if len(ns) > 1}


# Auto-register all built-in adapters on import.
def _bootstrap() -> None:
    from engine.adapters import rappter, ghost, swarm  # noqa: F401  (side effect: register)


_bootstrap()


__all__ = [
    "EngineAdapter",
    "register",
    "get",
    "all_engines",
    "names",
    "domain_overlap",
]
