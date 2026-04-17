#!/usr/bin/env python3
from __future__ import annotations

"""RAR Registry — Browse, search, and fetch agents from kody-w/RAR.

The RAPP Agent Registry (kody-w/RAR) is a public catalog of 138+ AI agents
published under BasicAgent contract. This brainstem agent lets any
Rappterbook agent discover, inspect, and pull agent source from RAR without
leaving the platform. Zero deps — pure stdlib (urllib + json).

Use for:
  - action="search"  — find agents by keyword
  - action="get"     — fetch full manifest of a specific agent
  - action="source"  — fetch .py source of a specific agent
  - action="stats"   — registry-wide stats (counts, publishers, categories)
  - action="list"    — list agents by category/publisher/tier
"""

import json
import urllib.request
import urllib.error
from pathlib import Path

AGENT = {
    "name": "RarRegistry",
    "description": (
        "Browse the RAPP Agent Registry (kody-w/RAR). Search 138+ agents by "
        "keyword, fetch manifests or source, list by category/publisher/tier, "
        "or get registry-wide stats. Stdlib only — hits raw.githubusercontent.com."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "What to do.",
                "enum": ["search", "get", "source", "stats", "list"],
            },
            "query": {
                "type": "string",
                "description": "Search query (for action=search) — matches name, "
                               "display_name, description, tags, category, author.",
            },
            "name": {
                "type": "string",
                "description": "Agent name like '@rapp/basic_agent' (for action=get/source).",
            },
            "category": {
                "type": "string",
                "description": "Filter by category (e.g. 'b2b_sales', 'healthcare').",
            },
            "publisher": {
                "type": "string",
                "description": "Filter by publisher namespace (e.g. '@rapp').",
            },
            "tier": {
                "type": "string",
                "description": "Filter by quality tier.",
                "enum": ["community", "verified", "official"],
            },
            "limit": {
                "type": "integer",
                "description": "Max results to return (default 25).",
            },
        },
        "required": ["action"],
    },
}

_BASE = "https://raw.githubusercontent.com/kody-w/RAR/main"
_REGISTRY_URL = f"{_BASE}/registry.json"
_UA = "rappterbook-rar-twin/1.0"


def _http_get(url: str, timeout: int = 15) -> str:
    """Fetch a URL as text. Raises on non-2xx."""
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def _load_registry() -> dict:
    """Fetch registry.json from RAR. Cached per-process via module global."""
    global _REG_CACHE
    cached = globals().get("_REG_CACHE")
    if cached is not None:
        return cached
    raw = _http_get(_REGISTRY_URL)
    _REG_CACHE = json.loads(raw)
    globals()["_REG_CACHE"] = _REG_CACHE
    return _REG_CACHE


def _matches(agent: dict, q: str) -> bool:
    """Fuzzy-ish match: substring in any field."""
    if not q:
        return True
    blob = json.dumps(agent).lower()
    return q.lower() in blob


def _thin(agent: dict) -> dict:
    """Trim an agent entry for API responses."""
    return {
        "name": agent.get("name"),
        "display_name": agent.get("display_name"),
        "description": agent.get("description"),
        "version": agent.get("version"),
        "category": agent.get("category"),
        "tier": agent.get("quality_tier"),
        "tags": agent.get("tags", [])[:8],
        "author": agent.get("author"),
        "file": agent.get("_file"),
        "seed": agent.get("_seed"),
        "lines": agent.get("_lines"),
    }


def _search(reg: dict, query: str, category: str, publisher: str, tier: str, limit: int) -> dict:
    """Search + filter the registry."""
    agents = reg.get("agents", [])
    if category:
        agents = [a for a in agents if a.get("category") == category]
    if publisher:
        agents = [a for a in agents if a.get("name", "").startswith(publisher + "/")]
    if tier:
        agents = [a for a in agents if a.get("quality_tier") == tier]
    if query:
        agents = [a for a in agents if _matches(a, query)]
    return {
        "count": len(agents),
        "limit": limit,
        "results": [_thin(a) for a in agents[:limit]],
    }


def _get(reg: dict, name: str) -> dict:
    """Fetch a single agent manifest by name."""
    for a in reg.get("agents", []):
        if a.get("name") == name or a.get("name", "").endswith("/" + name):
            return {"found": True, "agent": a}
    return {"found": False, "error": f"Agent '{name}' not found in registry."}


def _source(reg: dict, name: str) -> dict:
    """Fetch .py source of a registered agent."""
    found = _get(reg, name)
    if not found.get("found"):
        return found
    file_path = found["agent"].get("_file")
    url = f"{_BASE}/{file_path}"
    try:
        src = _http_get(url)
        return {
            "found": True,
            "name": found["agent"].get("name"),
            "file": file_path,
            "url": url,
            "bytes": len(src),
            "source": src,
        }
    except urllib.error.URLError as exc:
        return {"found": False, "error": f"Failed to fetch source: {exc}"}


def _stats(reg: dict) -> dict:
    """Registry-wide stats."""
    s = reg.get("stats", {})
    agents = reg.get("agents", [])
    by_tier: dict[str, int] = {}
    for a in agents:
        t = a.get("quality_tier", "unknown")
        by_tier[t] = by_tier.get(t, 0) + 1
    return {
        "total_agents": s.get("total_agents", len(agents)),
        "publishers": s.get("publishers"),
        "categories": s.get("categories"),
        "publisher_list": s.get("publisher_list", []),
        "category_list": s.get("category_list", []),
        "by_tier": by_tier,
        "generated_at": reg.get("generated_at"),
    }


def _list(reg: dict, category: str, publisher: str, tier: str, limit: int) -> dict:
    """List agents filtered by category/publisher/tier (no text query)."""
    return _search(reg, "", category, publisher, tier, limit)


def run(context: dict, **kwargs) -> dict:
    """Route to a sub-action."""
    action = kwargs.get("action", "").strip()
    if action not in {"search", "get", "source", "stats", "list"}:
        return {"status": "error", "error": f"Unknown action '{action}'. Use: search|get|source|stats|list"}

    try:
        reg = _load_registry()
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        return {"status": "error", "error": f"Failed to load RAR registry: {exc}"}

    limit = int(kwargs.get("limit") or 25)

    if action == "stats":
        return {"status": "ok", "action": "stats", "data": _stats(reg)}

    if action == "search":
        return {"status": "ok", "action": "search", "data": _search(
            reg,
            kwargs.get("query", ""),
            kwargs.get("category", ""),
            kwargs.get("publisher", ""),
            kwargs.get("tier", ""),
            limit,
        )}

    if action == "list":
        return {"status": "ok", "action": "list", "data": _list(
            reg,
            kwargs.get("category", ""),
            kwargs.get("publisher", ""),
            kwargs.get("tier", ""),
            limit,
        )}

    name = kwargs.get("name", "").strip()
    if not name:
        return {"status": "error", "error": f"'name' is required for action={action}"}

    if action == "get":
        result = _get(reg, name)
        return {"status": "ok" if result.get("found") else "not_found", "action": "get", "data": result}

    if action == "source":
        result = _source(reg, name)
        return {"status": "ok" if result.get("found") else "not_found", "action": "source", "data": result}

    return {"status": "error", "error": "unreachable"}


if __name__ == "__main__":
    import sys
    act = sys.argv[1] if len(sys.argv) > 1 else "stats"
    kw: dict = {"action": act}
    for arg in sys.argv[2:]:
        if "=" in arg:
            k, v = arg.split("=", 1)
            kw[k] = v
    print(json.dumps(run({}, **kw), indent=2)[:4000])
