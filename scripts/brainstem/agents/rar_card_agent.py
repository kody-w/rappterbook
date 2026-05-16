#!/usr/bin/env python3
from __future__ import annotations

"""RAR Card Resolver — Deterministically resolve a holographic agent card
from any numeric seed OR from an agent name. Same mulberry32 algorithm as
the RAR binder (kody-w/RAR/binder.html). Offline after first call, no deps.

A card has:
  - agent_types (1-2 of LOGIC/DATA/SOCIAL/SHIELD/CRAFT/HEAL/WEALTH)
  - stats (HP, ATK, DEF, SPD, INT — each 10-100)
  - typed abilities (name, cost, damage, text)
  - matchup (weakness + resistance via type wheel)
  - rarity (common/uncommon/rare/legendary)

Use for:
  - action="resolve_seed" — numeric seed → card
  - action="resolve_name" — agent name → looked up in registry → seed → card
  - action="battle"       — two cards → matchup analysis + hypothetical winner
"""

import json
import urllib.request
from pathlib import Path

AGENT = {
    "name": "RarCardResolver",
    "description": (
        "Resolve a holographic RAPP agent card from a numeric seed or an agent "
        "name. Same deterministic algorithm as the RAR binder — offline-capable, "
        "stdlib only. Supports hypothetical card-vs-card battle analysis."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["resolve_seed", "resolve_name", "battle"],
                "description": "What to do.",
            },
            "seed": {
                "type": "string",
                "description": "Numeric seed (string to avoid precision loss).",
            },
            "name": {
                "type": "string",
                "description": "Agent name like '@rapp/basic_agent' (for resolve_name/battle).",
            },
            "vs_name": {
                "type": "string",
                "description": "Opponent agent name (for action=battle).",
            },
            "display_name": {
                "type": "string",
                "description": "Optional human-readable label to attach to the card.",
            },
        },
        "required": ["action"],
    },
}

_BASE = "https://raw.githubusercontent.com/kody-w/RAR/main"
_UA = "rappterbook-rar-twin/1.0"

_TYPES = ["LOGIC", "DATA", "SOCIAL", "SHIELD", "CRAFT", "HEAL", "WEALTH"]

# Type wheel: LOGIC > DATA > SOCIAL > SHIELD > CRAFT > HEAL > WEALTH > LOGIC
_MATCHUP = {
    "LOGIC":  {"weak_to": "WEALTH",  "resists": "DATA"},
    "DATA":   {"weak_to": "LOGIC",   "resists": "SOCIAL"},
    "SOCIAL": {"weak_to": "DATA",    "resists": "SHIELD"},
    "SHIELD": {"weak_to": "SOCIAL",  "resists": "CRAFT"},
    "CRAFT":  {"weak_to": "SHIELD",  "resists": "HEAL"},
    "HEAL":   {"weak_to": "CRAFT",   "resists": "WEALTH"},
    "WEALTH": {"weak_to": "HEAL",    "resists": "LOGIC"},
}

_ABILITY_POOL = [
    {"name": "Forecast",  "text": "Project future values from historical patterns.", "cost": 2, "damage": 16},
    {"name": "Close",     "text": "Execute final steps of value exchange.",           "cost": 1, "damage": 39},
    {"name": "Query",     "text": "Extract structured data from noisy input.",        "cost": 1, "damage": 22},
    {"name": "Pipeline",  "text": "Chain multi-step operations deterministically.",   "cost": 2, "damage": 28},
    {"name": "Mesh",      "text": "Bind to neighbor agents, share telemetry.",        "cost": 3, "damage": 14},
    {"name": "Monitor",   "text": "Passive watcher — reacts on threshold breach.",    "cost": 2, "damage": 18},
    {"name": "Archive",   "text": "Persist snapshot, restore on request.",            "cost": 1, "damage": 12},
    {"name": "Configure", "text": "Orchestrate downstream agents.",                   "cost": 2, "damage": 20},
    {"name": "Synergy",   "text": "Gain +1/+1 per allied BasicAgent on the field.",   "cost": 1, "damage": 8},
]


def _mulberry32(seed: int):
    """Port of the RAR binder's mulberry32 PRNG. Returns a callable.
    Yields floats in [0,1). Deterministic per seed."""
    state = seed & 0xFFFFFFFF

    def _next() -> float:
        nonlocal state
        state = (state + 0x6D2B79F5) & 0xFFFFFFFF
        t = state
        t = ((t ^ (t >> 15)) * (t | 1)) & 0xFFFFFFFF
        t = (t ^ (t + (((t ^ (t >> 7)) * (t | 61)) & 0xFFFFFFFF))) & 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296.0

    return _next


def _seed_from_name(name: str) -> int:
    """FNV-1a 64-bit hash — matches rapp_sdk.card_mint seed forge."""
    h = 0xcbf29ce484222325
    for ch in name:
        h ^= ord(ch)
        h = (h * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
    return h


def _resolve(seed: int, display_name: str) -> dict:
    """Run the deterministic card-forge algorithm."""
    rng = _mulberry32(seed)
    primary = _TYPES[int(rng() * 7)]
    secondary_idx = int(rng() * 7)
    secondary = _TYPES[secondary_idx]
    if secondary == primary:
        secondary = _TYPES[(secondary_idx + 1) % 7]

    stats = {
        "hp":  40 + int(rng() * 60),
        "atk": 30 + int(rng() * 60),
        "def": 20 + int(rng() * 60),
        "spd": 30 + int(rng() * 60),
        "int": 40 + int(rng() * 60),
    }

    abils = [_ABILITY_POOL[int(rng() * len(_ABILITY_POOL))]]
    if rng() > 0.35:
        abils.append(_ABILITY_POOL[int(rng() * len(_ABILITY_POOL))])

    r = rng()
    rarity = "legendary" if r < 0.05 else "rare" if r < 0.2 else "uncommon" if r < 0.5 else "common"

    return {
        "display_name": display_name,
        "seed": str(seed),
        "agent_types": [primary, secondary],
        "primary_type": primary,
        "stats": stats,
        "power_score": sum(stats.values()),
        "typed_abilities": abils,
        "weakness": _MATCHUP[primary]["weak_to"],
        "resistance": _MATCHUP[primary]["resists"],
        "rarity": rarity,
        "floor_pts": 20 + int(rng() * 80),
    }


def _http_get(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def _lookup_name(name: str) -> tuple[int, str]:
    """Resolve an agent name to (seed, display_name). Falls back to hashing."""
    try:
        raw = _http_get(f"{_BASE}/registry.json")
        reg = json.loads(raw)
        for a in reg.get("agents", []):
            if a.get("name") == name or a.get("name", "").endswith("/" + name):
                seed = a.get("_seed")
                if seed is not None:
                    return int(seed), a.get("display_name", name)
    except Exception:  # noqa: BLE001 — fallback silently
        pass
    return _seed_from_name(name), name


def _battle(card_a: dict, card_b: dict) -> dict:
    """Compare two cards. Surface matchup effects and a hypothetical winner."""
    a_primary = card_a["primary_type"]
    b_primary = card_b["primary_type"]
    a_advantage = _MATCHUP[a_primary]["weak_to"] == b_primary  # b is weak to a? No — weak_to means a is weak to
    # Wheel: X > Y means X beats Y. weak_to[X] is the type X is weak to. So X beats resists[X].
    a_beats_b = _MATCHUP[a_primary]["resists"] == b_primary
    b_beats_a = _MATCHUP[b_primary]["resists"] == a_primary

    a_score = card_a["power_score"] * (1.25 if a_beats_b else 0.85 if b_beats_a else 1.0)
    b_score = card_b["power_score"] * (1.25 if b_beats_a else 0.85 if a_beats_b else 1.0)

    return {
        "a": {"name": card_a["display_name"], "type": a_primary, "power": card_a["power_score"], "adjusted": round(a_score, 1)},
        "b": {"name": card_b["display_name"], "type": b_primary, "power": card_b["power_score"], "adjusted": round(b_score, 1)},
        "type_advantage": "a" if a_beats_b else "b" if b_beats_a else "none",
        "winner": "a" if a_score > b_score else "b" if b_score > a_score else "draw",
        "margin": round(abs(a_score - b_score), 1),
    }


def run(context: dict, **kwargs) -> dict:
    """Route to a sub-action."""
    action = kwargs.get("action", "").strip()

    if action == "resolve_seed":
        seed_s = str(kwargs.get("seed") or "").strip()
        if not seed_s or not seed_s.lstrip("-").isdigit():
            return {"status": "error", "error": "'seed' must be a numeric string"}
        dn = kwargs.get("display_name", f"seed-{seed_s[:8]}")
        return {"status": "ok", "action": action, "card": _resolve(int(seed_s), dn)}

    if action == "resolve_name":
        name = (kwargs.get("name") or "").strip()
        if not name:
            return {"status": "error", "error": "'name' is required"}
        seed, dn = _lookup_name(name)
        card = _resolve(seed, kwargs.get("display_name") or dn)
        card["agent_name"] = name
        return {"status": "ok", "action": action, "card": card}

    if action == "battle":
        n1 = (kwargs.get("name") or "").strip()
        n2 = (kwargs.get("vs_name") or "").strip()
        if not n1 or not n2:
            return {"status": "error", "error": "'name' and 'vs_name' are required"}
        s1, d1 = _lookup_name(n1)
        s2, d2 = _lookup_name(n2)
        c1 = _resolve(s1, d1)
        c2 = _resolve(s2, d2)
        return {
            "status": "ok", "action": action,
            "card_a": c1, "card_b": c2,
            "battle": _battle(c1, c2),
        }

    return {"status": "error", "error": f"Unknown action '{action}'. Use: resolve_seed|resolve_name|battle"}


if __name__ == "__main__":
    import sys
    act = sys.argv[1] if len(sys.argv) > 1 else "resolve_seed"
    kw: dict = {"action": act}
    for arg in sys.argv[2:]:
        if "=" in arg:
            k, v = arg.split("=", 1)
            kw[k] = v
    print(json.dumps(run({}, **kw), indent=2))
