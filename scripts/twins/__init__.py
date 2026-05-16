"""Rappter twin engines — registry of public-facing engines that the
treaty router can address by id.

Each twin engine is a small module that:
  * defines an `ENGINE` :class:`TwinEngine` instance
  * calls :func:`register` at import time
  * exposes one or more action handlers (params dict in -> result dict out)

Outside sources address an engine by id in their treaty ping:

    {"engine": "templates", "action": "tick", ...}
    {"engine": "slop",      "action": "diagnose", ...}
    {"engine": "meta",      "action": "list", ...}

Engines coexist independently. Adding a new engine = drop a file in
this package; the registry picks it up via `_load_builtins()`.
"""
from __future__ import annotations

import importlib
import pkgutil
import sys
from pathlib import Path
from typing import Callable

# Make sibling scripts/ modules importable from inside engine handlers
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


class TwinEngine:
    """A self-contained twin with its own action vocabulary."""

    def __init__(self, id: str, version: str, description: str,
                 actions: dict[str, Callable[[dict], dict]]):
        if not id.isidentifier():
            raise ValueError(f"engine id must be a Python identifier: {id!r}")
        self.id = id
        self.version = version
        self.description = description
        self.actions = actions

    def manifest(self) -> dict:
        return {
            "id": self.id,
            "version": self.version,
            "description": self.description,
            "actions": sorted(self.actions.keys()),
        }

    def dispatch(self, action: str, params: dict) -> dict:
        if action not in self.actions:
            raise ValueError(
                f"engine {self.id!r} has no action {action!r}; "
                f"valid: {sorted(self.actions.keys())}"
            )
        return self.actions[action](params or {})


REGISTRY: dict[str, TwinEngine] = {}


def register(engine: TwinEngine) -> None:
    """Add (or replace) an engine in the registry."""
    REGISTRY[engine.id] = engine


def get(engine_id: str) -> TwinEngine | None:
    return REGISTRY.get(engine_id)


def list_engines() -> list[dict]:
    return [REGISTRY[k].manifest() for k in sorted(REGISTRY.keys())]


def _load_builtins() -> None:
    """Auto-import every twin module so it can self-register."""
    pkg_path = Path(__file__).resolve().parent
    for mod_info in pkgutil.iter_modules([str(pkg_path)]):
        if mod_info.name.startswith("_") or mod_info.name == "test":
            continue
        importlib.import_module(f"{__name__}.{mod_info.name}")


_load_builtins()
