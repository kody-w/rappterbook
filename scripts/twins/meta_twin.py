"""Meta twin engine — registry / discovery.

Lets outside sources discover what engines are available and what
actions each engine accepts. Every multi-engine bus needs an
introspection endpoint.
"""
from __future__ import annotations

from . import REGISTRY, TwinEngine, list_engines, register


def _list(_params: dict) -> dict:
    return {
        "engines": list_engines(),
        "count": len(REGISTRY),
    }


def _describe(params: dict) -> dict:
    eid = params.get("engine_id") or params.get("id")
    if not eid:
        raise ValueError("params.engine_id required")
    eng = REGISTRY.get(eid)
    if eng is None:
        return {"engine_id": eid, "found": False,
                "available": sorted(REGISTRY.keys())}
    return {"engine_id": eid, "found": True, "manifest": eng.manifest()}


def _status(_params: dict) -> dict:
    return {"alive": True, "engines": sorted(REGISTRY.keys())}


ENGINE = TwinEngine(
    id="meta",
    version="1.0",
    description="Registry / discovery for the twin bus. Use action=list to "
                "enumerate engines, action=describe with params.engine_id for details.",
    actions={"list": _list, "describe": _describe, "status": _status},
)
register(ENGINE)
